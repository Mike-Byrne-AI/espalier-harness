#!/usr/bin/env python3
"""What ``espalier/cli.py`` costs a maintainer, read at one pinned commit.

The instrument of the cli.py audit (wave 0 of the roadmap
``task-packs/TP-708-the-cli-is-mapped-before-it-moves.md``). Every section is
read at ``--at``, a commit with no default. Every source text comes from git's
objects at that commit, never from the working tree, and every window is
anchored to the commit's date, never to the clock. A run without ``--at``
refuses, so two runs at one pin read one population.

    python3 scripts/cli_cost_census.py --at <P> --json                  # every section
    python3 scripts/cli_cost_census.py --at <P> functions layers        # named sections
    python3 scripts/cli_cost_census.py --at <P> collision transcripts   # Task 0's two oracles

"The CLI modules" are ``espalier/cli.py`` plus every module that receives a
definition moved out of it (``--module``, repeatable). Every component counts
over the whole set, so a move cannot zero a component by changing which file
the events land on.

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
import functools
import importlib.util
import itertools
import json
import os
import re
import shutil
import statistics
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = "espalier/cli.py"
#: The windowed components read the 30 days to the pin's commit date.
WINDOW_DAYS = 30
SECTIONS = ("pin", "functions", "layers", "clusters", "importers", "readers", "patches",
            "citations", "probes", "doctor_boundary", "ledger_rows", "collision", "transcripts",
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
    """``path``'s text at commit ``at``, or ``None`` where the commit has no such file."""
    rc, out, _err = git(root, "show", f"{at}:{path}")
    return out if rc == 0 else None


def tracked_at(root: Path, at: str) -> list[str]:
    rc, out, err = git(root, "ls-tree", "-r", "--name-only", at)
    if rc != 0:
        raise Unread(f"git ls-tree {at} failed: {err.strip()}")
    return [line for line in out.splitlines() if line]


def blobs_at(root: Path, at: str, paths: list[str]) -> dict[str, str]:
    """Each path's text at ``at``, read in one ``git cat-file --batch``. A path
    git cannot read is left out, so a caller counts what it read."""
    if not paths:
        return {}
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    proc = run_bounded(["git", "cat-file", "--batch"], input="".join(f"{at}:{p}\n" for p in paths).encode(),
                       capture_output=True, timeout=GIT_TIMEOUT, env=env, cwd=str(root))
    if proc.returncode != 0:
        raise Unread(f"git cat-file --batch at {at[:12]} failed")
    data, out, pos = proc.stdout, {}, 0
    for path in paths:
        end = data.index(b"\n", pos)
        header = data[pos:end].split()
        pos = end + 1
        if len(header) < 3 or header[1] != b"blob":
            continue
        size = int(header[2])
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


def _locally_bound(node: ast.AST) -> tuple[set[str], set[str]]:
    """``(bound, declared_global)`` over a definition and every scope nested in
    it. A load of a module name that the definition binds locally reads the
    local; a name declared ``global`` anywhere in it is the module's."""
    bound: set[str] = set()
    declared: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Global, ast.Nonlocal)):
            if isinstance(sub, ast.Global):
                declared.update(sub.names)
        elif isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
            bound.add(sub.id)
        elif isinstance(sub, ast.arg):
            bound.add(sub.arg)
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and sub is not node:
            bound.add(sub.name)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            bound.update((a.asname or a.name).split(".")[0] for a in sub.names)
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            bound.add(sub.name)
    return bound - declared, declared


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
    definition (its outbound edge to another module)."""
    names = {d["name"] for d in defs}
    aliases = _module_aliases(tree)
    loads: dict[str, set[str]] = {n: set() for n in names}
    writes: dict[str, set[str]] = {n: set() for n in names}
    unresolved: dict[str, dict] = {}
    for d in defs:
        node, me = d["node"], d["name"]
        if d["kind"] == NAME:
            local: set[str] = set()
            declared: set[str] = set()
            walk_root = node.value if getattr(node, "value", None) is not None else node
        else:
            local, declared = _locally_bound(node)
            walk_root = node
        u = unresolved.setdefault(me, {"getattr": 0, "string_names": 0, "through_module": 0,
                                       "lazy_imports": []})
        for sub in ast.walk(walk_root):
            if isinstance(sub, ast.Name):
                if sub.id not in names or sub.id == me and d["kind"] == NAME:
                    continue
                if isinstance(sub.ctx, ast.Load) and (sub.id not in local or sub.id in declared):
                    loads[me].add(sub.id)
                elif isinstance(sub.ctx, (ast.Store, ast.Del)) and sub.id in declared:
                    writes[me].add(sub.id)
            elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "getattr":
                if len(sub.args) >= 2 and isinstance(sub.args[1], ast.Constant):
                    u["getattr"] += 1
            elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value in names:
                u["string_names"] += 1
            elif (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                  and sub.value.id in aliases and sub.value.id not in local):
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
        "lines": len(text.splitlines()) if text else 0,
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
    and ``dead`` is then no claim. Each split is
    given over every definition and over functions alone, and the census
    asserts the sum."""
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
            files = _importers(ctx)["files"].values()
        except Unread:
            files = None
        if files is not None:
            external = sorted({n for f in files if not f["test"] for n in f["names"]})
            tested = sorted({n for f in files if f["test"] for n in f["names"]})
    outside = closure(edges, [n for n in external or () if n in edges], stop=set(commands))
    in_tests = closure(edges, [n for n in tested or () if n in edges], stop=set(commands))
    fns = {n for n in edges if kinds[n] == FUNCTION}
    total_lines = sum(lines[n] for n in fns)
    file_lines = len((source_at(ctx["root"], ctx["pin"]["at"], CLI) or "").splitlines())
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
                "unreached_dead": sorted(rest - outside - in_tests),
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
    a function or class body: an outbound edge that loads at call time."""
    top = {id(n) for n in tree.body}
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
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                chain, cur = [], node.value
                while isinstance(cur, ast.Attribute):
                    chain.insert(0, cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name) and [cur.id, *chain] == dotted:
                    names.add(node.attr)
        out.append({"names": sorted(names), "line": None, "lazy": lazy, "via": f"alias {alias}"})
    return out


def _importers(ctx: dict) -> dict:
    if "_importers" in ctx:
        return ctx["_importers"]
    root, at = ctx["root"], ctx["pin"]["at"]
    tracked = tracked_at(root, at)
    py = [p for p in tracked if p.endswith(".py") and p not in ctx["modules"]]
    texts = blobs_at(root, at, py)
    files: dict[str, dict] = {}
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
    ctx["_importers"] = {"files": files, "unparsed": unparsed, "read": len(texts), "tracked_py": len(py),
                         "tracked": tracked}
    return ctx["_importers"]


def section_importers(ctx: dict) -> dict:
    """Who imports cli at the pin, by AST over every tracked ``.py`` file:
    each file with the names it takes, whether lazily, and the totals outside
    tests and in them, kept apart. Then the two runs no move may change: the
    console entry in ``pyproject.toml`` and each tracked file that runs
    ``python -m espalier.cli`` (read as text, every file type)."""
    imp = _importers(ctx)
    root, at = ctx["root"], ctx["pin"]["at"]
    outside = {p: f for p, f in imp["files"].items() if not f["test"]}
    tests = {p: f for p, f in imp["files"].items() if f["test"]}
    pyproject = source_at(root, at, "pyproject.toml")
    texts = blobs_at(root, at, [p for p in imp["tracked"] if p not in ctx["modules"]])
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


def cli_aliases(tree: ast.Module) -> set[str]:
    """The dotted names a test file binds to the cli module itself: ``from
    espalier import cli [as x]``, ``import espalier.cli [as x]`` and
    ``x = importlib.import_module("espalier.cli")``, anywhere in the file."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "espalier" and not node.level:
            out.update(a.asname or "cli" for a in node.names if a.name == "cli")
        elif isinstance(node, ast.Import):
            out.update(a.asname or CLI_MODULE for a in node.names if a.name == CLI_MODULE)
        elif (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
              and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "import_module"
              and node.value.args and isinstance(node.value.args[0], ast.Constant)
              and node.value.args[0].value == CLI_MODULE):
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


def patch_sites(tree: ast.Module) -> list[dict]:
    """Each site in one test file that patches a name on cli: a patcher
    called on an alias of cli and a constant name (``setattr(cli, "X", ...)``,
    ``patch.object(cli, "X")``, ``delattr``), a string target
    (``"espalier.cli.X"``), or an assignment ``cli.X = ...``. A patcher called
    on an attribute OF cli (``setattr(cli.shutil, "which", ...)``) patches
    another module through cli: ``through`` names it."""
    aliases = cli_aliases(tree)
    sites: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            last = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
            kind = _PATCHERS.get(last or "")
            if kind is None or not node.args:
                continue
            raising = next((k.value for k in node.keywords if k.arg == "raising"), None)
            raising_false = isinstance(raising, ast.Constant) and raising.value is False
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value.startswith(CLI_MODULE + "."):
                rest = first.value[len(CLI_MODULE) + 1:]
                sites.append({"target": rest.split(".")[0], "through": rest if "." in rest else None,
                              "kind": kind, "spelling": "string", "line": node.lineno, "raising_false": raising_false})
                continue
            owner = _dotted(first)
            if owner is None:
                continue
            name = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else None
            if owner in aliases and isinstance(name, str):
                sites.append({"target": name, "through": None, "kind": kind, "spelling": "alias",
                              "line": node.lineno, "raising_false": raising_false})
            elif any(owner.startswith(a + ".") for a in aliases):
                attr = owner.split(".", len(next(a for a in aliases if owner.startswith(a + ".")).split(".")))[-1]
                sites.append({"target": attr.split(".")[0], "through": f"{attr}.{name}" if isinstance(name, str) else attr,
                              "kind": kind, "spelling": "alias", "line": node.lineno, "raising_false": raising_false})
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Attribute) and _dotted(t.value) in aliases:
                    sites.append({"target": t.attr, "through": None, "kind": "assign", "spelling": "alias",
                                  "line": node.lineno, "raising_false": False})
    return sites


def section_patches(ctx: dict) -> dict:
    """The test patches on cli at the pin, by AST over ``tests/``: distinct
    targets, sites and files; which targets cli defines and which it imports
    from elsewhere (a new module gets its own binding of those); how many
    definitions in cli load each target (a target with more than one loader
    stays green under a partial move); ``raising=False`` sites, which create a
    missing attribute in silence; and the patches of another module through
    cli. Every figure is over the CLI modules' first entry, ``espalier/cli.py``."""
    root, at = ctx["root"], ctx["pin"]["at"]
    tests = [p for p in tracked_at(root, at) if p.startswith("tests/") and p.endswith(".py")]
    texts = blobs_at(root, at, tests)
    tree_cli, defs = parse_cli(root, at)
    defined = {d["name"] for d in defs}
    by_file: dict[str, list[dict]] = {}
    unparsed = []
    for path in sorted(texts):
        if "cli" not in texts[path]:
            continue
        try:
            found = patch_sites(ast.parse(texts[path]))
        except (SyntaxError, ValueError):
            unparsed.append(path)
            continue
        if found:
            by_file[path] = found
    on_cli = [(p, s) for p, ss in by_file.items() for s in ss if s["through"] is None]
    through = [(p, s) for p, ss in by_file.items() for s in ss if s["through"] is not None]
    targets = sorted({s["target"] for _p, s in on_cli})
    loaders = {t: 0 for t in targets}
    for d in defs:
        if d["kind"] == NAME:
            continue
        local, declared = _locally_bound(d["node"])
        seen = {n.id for n in ast.walk(d["node"]) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                and (n.id not in local or n.id in declared)}
        for t in targets:
            if t in seen and t != d["name"]:
                loaders[t] += 1
    sites_of = {t: sum(1 for _p, s in on_cli if s["target"] == t) for t in targets}
    multi = [t for t in targets if loaders[t] > 1]
    imported = [t for t in targets if t not in defined]
    raising = {t: {"sites": sites_of[t], "raising_false": sum(1 for _p, s in on_cli if s["target"] == t and s["raising_false"])}
               for t in targets if any(s["target"] == t and s["raising_false"] for _p, s in on_cli)}
    return {"rule": "ast over tests/: a patcher on an alias of espalier.cli with a constant name, a string target "
                    "'espalier.cli.X', or an assignment to an attribute of the alias",
            "files": len({p for p, _s in on_cli}), "sites": len(on_cli), "targets": len(targets),
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
    parents, its committer date and its subject. One ``git log``."""
    rc, out, err = git(root, "log", "--merges", "--format=%H%x1f%P%x1f%cI%x1f%s", at)
    if rc != 0:
        raise Unread(f"git log --merges {at[:12]} failed: {err.strip()}")
    rows = []
    for line in out.splitlines():
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
    return [{"oid": a, "messageHeadline": b} for a, _sep, b in (l.partition("\x1f") for l in out.splitlines())]


def lane_files(root: Path, pr: dict) -> tuple[str, list[str]]:
    """``(merge-base, paths)``: what the lane changed against the base it
    branched from, at its merge (``git diff --name-only <merge-base> <head>``)."""
    rc, out, err = git(root, "merge-base", pr["base"], pr["head"])
    if rc != 0 or not out.strip():
        raise Unread(f"no merge-base for #{pr['number']}: {err.strip()}")
    mb = out.strip()
    rc, out, err = git(root, "diff", "--name-only", mb, pr["head"])
    if rc != 0:
        raise Unread(f"git diff {mb[:12]} {pr['head'][:12]} failed: {err.strip()}")
    return mb, [p for p in out.splitlines() if p]


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
    --json number,createdAt,mergedAt``) or from ``gh``, every number to #1."""
    if "_pr_meta" in ctx:
        return ctx["_pr_meta"]
    path = ctx.get("prs_json")
    if path:
        listed = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        proc = run_bounded(["gh", "pr", "list", "--state", "merged", "--limit", "1000", "--json",
                            "number,createdAt,mergedAt"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=GIT_TIMEOUT, cwd=str(ctx["root"]))
        if proc.returncode != 0:
            raise Unread(f"gh pr list failed: {proc.stderr.strip()[:200]}")
        listed = json.loads(proc.stdout or "[]")
    ctx["_pr_meta"] = {int(p["number"]): {"created": _stamp(p["createdAt"]), "merged": _stamp(p["mergedAt"])}
                       for p in listed if p.get("createdAt") and p.get("mergedAt")}
    return ctx["_pr_meta"]


def mail_refs(root: Path) -> dict[str, str]:
    """``{machine: oid}`` of each remote-tracking mail ref: read once, at the
    start of a run, and written into the pin, so a re-run names what it read."""
    rc, out, _err = git(root, "for-each-ref", "--format=%(objectname) %(refname)", "refs/remotes/origin/mail/")
    if rc != 0:
        return {}
    refs = {}
    for line in out.splitlines():
        oid, _sp, ref = line.partition(" ")
        refs[ref.rsplit("/", 1)[-1]] = oid
    return refs


def mail_at(ctx: dict) -> dict[str, list[dict]]:
    """Every machine's messages at the pinned mail oids, cut at the pin's
    date by each message's own stamp: a message sent after P is not in a
    read at P, whatever the ref holds now."""
    if "_mail_at" in ctx:
        return ctx["_mail_at"]
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
    return out


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
    hand read that confirms each (a word match is a candidate, never a hold)."""
    disp = dispatcher_at(ctx)
    if disp is None:
        raise Unread("espalier.toml at the pin names no usable dispatcher")
    messages = mail_at(ctx).get(disp, [])
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
    first = messages[0]["at"] if messages else None
    days = None
    if first:
        days = round((datetime.fromisoformat(ctx["pin"]["window"]["until"].replace("Z", "+00:00"))
                      - datetime.fromisoformat(first.replace("Z", "+00:00"))).total_seconds() / 86400, 1)
    return {"dispatcher": disp, "record_from": first, "record_days": days, "messages": len(messages),
            "declared": declared, "named_in_text": in_text}


def catch_ups_carrying(ctx: dict) -> dict:
    """Context, never a cost (the up-to-date rule is off): the window's
    catch-up merges whose base side brought a CLI module change into a lane
    (``git diff --name-only <catch-up>^1 <catch-up>``)."""
    root, at = ctx["root"], ctx["pin"]["at"]
    catch = _merge_cost().CATCH_UP
    count = carrying = 0
    for m in merges_at(root, at):
        if not catch.match(m["subject"]) or not _in_window(m["date"], ctx["pin"]["window"]):
            continue
        count += 1
        rc, out, _err = git(root, "diff", "--name-only", m["parents"][0], m["oid"])
        if rc == 0 and _touches_cli(out.splitlines(), ctx["modules"]):
            carrying += 1
    return {"graded": False, "catch_ups_in_window": count, "carrying_a_cli_module": carrying}


def section_collision(ctx: dict) -> dict:
    """Task 0 Item 2's oracle: the four components, each with its window and
    its count of CLI-module pull requests. A component that cannot be read is
    named under the section's own ``unread``, never a zero."""
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
        except Unread as exc:
            out[key] = None
            out["unread"][key] = str(exc)
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
    in at the merge-base, and their lengths summed there."""
    text = source_at(root, mb, module)
    if text is None:
        return {"definitions": [], "lines": 0}
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
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_SAVED = re.compile(r"(?:Full output|Output) saved to:?\s*(\S+/tool-results/\S+)")


def project_folder(path: str) -> str:
    """Claude Code's project folder name for a checkout path."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def checkouts(root: Path) -> list[dict]:
    """Each checkout of this clone (``git worktree list``), its seat name
    (``espalier.machine``, the per-worktree one first) and its project folder."""
    rc, out, _err = git(root, "worktree", "list", "--porcelain")
    paths = [line[len("worktree "):] for line in out.splitlines() if line.startswith("worktree ")] if rc == 0 else []
    rows = []
    for p in paths:
        rc, name, _err = git(Path(p), "config", "--get", "espalier.machine") if Path(p).is_dir() else (1, "", "")
        rows.append({"path": p, "seat": name.strip() or None, "folder": project_folder(p)})
    return rows


def strip_heredocs(command: str) -> str:
    """The command with every here-document's body taken out: a path inside
    one is the text of a message or a script, never a read."""
    out, lines, i = [], command.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        tags = [m.group(2) for m in _HEREDOC.finditer(line)]
        i += 1
        for tag in tags:
            while i < len(lines) and lines[i].strip() != tag:
                i += 1
            i += 1
    return "\n".join(out)


def simple_commands(command: str) -> list[tuple[list[str], bool]]:
    """``(argv, piped)`` for each simple command of a shell line, heredocs
    stripped: split on ``;``, ``&&``, ``||``, ``|``, ``&`` and newlines.
    ``piped`` marks one whose output goes into, or comes from, a pipe."""
    import shlex
    text = strip_heredocs(command).replace("\n", " ; ")
    lex = shlex.shlex(text, posix=True, punctuation_chars=";&|()")
    lex.whitespace_split = True
    try:
        tokens = list(lex)
    except ValueError:
        return []
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
    whole file (or a range it cannot tell)."""
    if program == "sed":
        total, saw = 0, False
        for a in args:
            m = re.fullmatch(r"(\d+)(?:,(\d+))?p", a)
            if m:
                saw = True
                total += (int(m.group(2)) - int(m.group(1)) + 1) if m.group(2) else 1
        return total if saw else None
    if program in ("head", "tail"):
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


def read_operands(argv: list[str]) -> tuple[str, list[str], int | None] | None:
    """``(kind, files, range)`` for a read or a search, else ``None``.
    ``kind`` is ``read`` (the allowlist: ``sed`` without ``-i``, ``cat``,
    ``head``, ``tail``, ``nl``, ``awk``, ``git show <rev>:<path>``) or
    ``search``; the files are the whole operands the program reads."""
    while argv and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argv[0]):
        argv = argv[1:]
    if not argv:
        return None
    prog, args = Path(argv[0]).name, argv[1:]
    if prog == "git":
        while args[:1] == ["-C"] and len(args) > 1 or (args and args[0].startswith("-c")):
            args = args[2:] if args[0] in ("-C", "-c") else args[1:]
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
    skip_next, script_given = False, False
    for i, a in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if a in ("-e", "-f") and prog in ("sed", "awk"):
            skip_next, script_given = True, True
            continue
        if a == "-n" and prog in ("head", "tail"):
            skip_next = True
            continue
        if a.startswith("-") or a.startswith("+"):
            continue
        files.append(a)
    if prog in ("sed", "awk") and not script_given and files:
        files = files[1:]
    rng = _range(prog, args)
    return "read", files, rng


def _relative(path: str, cwd: str, roots: list[str]) -> str | None:
    full = os.path.normpath(path if os.path.isabs(path) else os.path.join(cwd or "", path))
    for r in sorted(roots, key=len, reverse=True):
        if full == r or full.startswith(r.rstrip("/") + "/"):
            return full[len(r.rstrip("/")) + 1:]
    return None


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def _line_count(text: str) -> int:
    return len(text.splitlines())


def calls_of(records: list[dict], roots: list[str], until: str, length) -> list[dict]:
    """One session's file reads and searches, by the ruled rules: each
    ``tool_use`` once (deduped by id), the blob records skipped, cut at the
    pin's date by each record's own stamp. Each call carries its stamp, its
    branch, and ``reads``: ``[(repo path, lines)]``. ``length(path)`` is a
    file's length at the pin (a piped or multi-file whole read's range)."""
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
                                                           "meta": r.get("toolUseResult")})
    saved: dict[str, list[str]] = {}   # a saved output's path -> the files whose read it holds
    calls = []
    for u in sorted(uses.values(), key=lambda u: (u["at"], u["id"])):
        res = results.get(u["id"]) or {"text": "", "meta": None}
        meta = res["meta"] if isinstance(res["meta"], dict) else {}
        call = {"id": u["id"], "at": u["at"], "branch": u["branch"], "reads": [], "searches": []}
        if u["name"] == "Read":
            fp = str(u["input"].get("file_path") or "")
            n = int((meta.get("file") or {}).get("numLines") or _line_count(res["text"]))
            if "/tool-results/" in fp:
                call["reads"] = [(src, n) for src in saved.get(fp, [])]
            else:
                rel = _relative(fp, u["cwd"], roots)
                if rel:
                    call["reads"] = [(rel, n)]
        elif u["name"] == "Grep":
            rel = _relative(str(u["input"].get("path") or ""), u["cwd"], roots)
            if rel:
                call["searches"] = [(rel, _line_count(res["text"]))]
        elif u["name"] == "Bash":
            out = str(meta.get("stdout") if meta.get("stdout") is not None else res["text"])
            hit = _SAVED.search(out)
            parts = simple_commands(str(u["input"].get("command") or ""))
            cwd = u["cwd"]
            reads, searches = [], []
            for argv, piped in parts:
                if argv[:1] == ["cd"] and len(argv) > 1:
                    cwd = os.path.normpath(os.path.join(cwd, argv[1]))
                    continue
                got = read_operands(argv)
                if got is None:
                    continue
                kind, files, rng = got
                rels = [r for r in (_relative(f, cwd, roots) for f in files) if r]
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
    unmeasured."""
    import math
    nt, nc = len(r), len(e)
    if nt < 2 or nc < 2:
        return {"verdict": "unmeasured", "why": f"arms of {nt} and {nc} lanes", "n_t": nt, "n_c": nc}
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


def _records(path: Path) -> tuple[int, list[dict]]:
    """``(record count, the records a call can be read from)`` of one
    transcript, streamed: a line holding neither a ``tool_use`` nor a
    ``tool_result`` is counted and never parsed (the folders run to gigabytes
    on an 8 GB box)."""
    count, keep = 0, []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            count += 1
            if '"tool_use"' not in line and '"tool_result"' not in line:
                continue
            try:
                keep.append(json.loads(line))
            except ValueError:
                continue
    return count, keep


def section_transcripts(ctx: dict) -> dict:
    """Task 0 Item 3's oracle: the lines of the CLI modules the seats' own
    reads returned, per merged lane of the seats on this box, against the
    lines a control lane's reads returned on the files it edited. Every
    population figure is in the output: the folders (matched case-
    insensitively), each file's record count up to the pin, and the calls
    no lane took. Subagents are counted apart, through their parent's
    ``Agent`` call. Two of the four seats, said on the section."""
    root, at = ctx["root"], ctx["pin"]["at"]
    until = ctx["pin"]["window"]["until"]
    base = Path(ctx.get("projects_dir") or Path.home() / ".claude" / "projects")
    if not base.is_dir():
        raise Unread(f"no transcript folder at {base}")
    outs = ctx.get("checkouts") or checkouts(root)
    by_lower = {p.name.lower(): p for p in base.iterdir() if p.is_dir()}
    folders = [(c, by_lower.get(c["folder"].lower())) for c in outs if c["seat"] in BOX_SEATS]
    missing = [c["folder"] for c, f in folders if f is None]
    if missing:
        raise Unread(f"transcript folder(s) missing: {missing}")
    roots = [c["path"] for c in outs]
    by_machine = mail_at(ctx)
    seats = _mail().lane_seats(by_machine)
    claims = claim_intervals(by_machine, until)
    lanes = {pr["branch"]: pr for pr in _window_prs(ctx) if seats.get(pr["branch"]) in BOX_SEATS}
    windows: dict[str, list[tuple[str, str, str]]] = {}
    for c in claims:
        if c["lane"] in lanes and c["machine"] == seats.get(c["lane"]):
            windows.setdefault(c["machine"], []).append((c["start"], c["end"], c["lane"]))

    @functools.lru_cache(maxsize=None)
    def length(path: str) -> int:
        return len((source_at(root, at, path) or "").splitlines())

    def lane_of(seat: str, branch: str, when: str) -> str:
        """The record's own branch where it names a unit; a branch naming any
        other lane is no unit (never re-placed by the clock); only the default
        branch or none falls back to the seat's claim windows."""
        if branch in lanes and seats.get(branch) == seat:
            return branch
        if branch and branch not in ("main", "master", "HEAD"):
            return "other branch"
        held = {lane for s, e, lane in windows.get(seat, []) if s <= when <= e}
        return held.pop() if len(held) == 1 else ("ambiguous" if held else "unattributed")

    population, own, subs = [], [], []
    for c, folder in folders:
        agent_calls: dict[str, tuple[str, str]] = {}
        files = sorted(folder.glob("*.jsonl"))
        counts = {}
        for f in files:
            counts[f.name], recs = _records(f)
            for call in calls_of(recs, roots, until, length):
                call.update(seat=c["seat"], session=f.stem, lane=lane_of(c["seat"], call["branch"], call["at"]))
                own.append(call)
            for r in recs:
                for item in ((r.get("message") or {}).get("content") or []) if r.get("type") == "assistant" else []:
                    if isinstance(item, dict) and item.get("type") == "tool_use" and item.get("name") in ("Agent", "Task"):
                        agent_calls[item["id"]] = (str(r.get("gitBranch") or ""), str(r.get("timestamp") or ""))
            del recs
        population.append({"seat": c["seat"], "folder": folder.name, "files": len(files),
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
            for call in calls_of(recs, roots, until, length):
                call.update(seat=c["seat"], session=log.stem, lane=lane_of(c["seat"], branch, when))
                subs.append(call)
    modules = set(ctx["modules"])

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
    return {"seats": list(BOX_SEATS), "of_seats": 4, "population": population,
            "cutoff": until, "lanes": len(lanes), "treatment": treatment, "control": control,
            "item3": verdict,
            "beside": {"r_share_of_total": [round(t["r"] / t["total"], 3) if t["total"] else None for t in treatment],
                       "search_calls_on_cli": sum(t["search_calls"] for t in treatment),
                       "subagent_r": sum(t["subagent_r"] for t in treatment),
                       "control_with_py_only": item3_verdict([t["r"] for t in treatment],
                                                             [c["e"] for c in control if c["has_py"]])},
            "calls": {"own": len(own), "subagents": len(subs), "not_on_a_lane": unplaced},
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
    "patches": section_patches,
    "collision": section_collision,
    "lane_read": section_lane_read,
    "transcripts": section_transcripts,
}


def census(root: Path, at: str, sections: list[str], *, modules: tuple[str, ...] = (CLI,),
           extra: dict | None = None) -> dict:
    """Every named section read at ``at``. A section that raises ``Unread``,
    or has no reader yet, is ``None`` under its key and named under ``unread``."""
    ctx = {"root": root, "pin": resolve_pin(root, at), "modules": modules, **(extra or {})}
    ctx["pin"].setdefault("mail_refs", (extra or {}).get("mail_refs") or mail_refs(root))
    result: dict = {"unread": {}}
    for name in sections:
        reader = SECTION_READERS.get(name)
        if reader is None:
            result[name] = None
            result["unread"][name] = "no reader for this section in this census"
            continue
        try:
            result[name] = reader(ctx)
        except Unread as exc:
            result[name] = None
            result["unread"][name] = str(exc)
    if "pin" not in result:
        result["pin"] = section_pin(ctx)
    return result


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
        else:
            print(f"{name}: {json.dumps(result[name], sort_keys=True, default=sorted)[:400]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
