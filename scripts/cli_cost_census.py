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
import json
import os
import sys
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


SECTION_READERS = {
    "pin": section_pin,
    "functions": section_functions,
    "layers": section_layers,
    "clusters": section_clusters,
    "importers": section_importers,
    "patches": section_patches,
}


def census(root: Path, at: str, sections: list[str], *, modules: tuple[str, ...] = (CLI,),
           extra: dict | None = None) -> dict:
    """Every named section read at ``at``. A section that raises ``Unread``,
    or has no reader yet, is ``None`` under its key and named under ``unread``."""
    ctx = {"root": root, "pin": resolve_pin(root, at), "modules": modules, **(extra or {})}
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
    args = ap.parse_args(argv)
    unknown = [s for s in args.sections if s not in SECTIONS]
    if unknown:
        ap.error(f"unknown section(s) {unknown}; choose from {', '.join(SECTIONS)}")
    sections = list(args.sections) or list(SECTIONS)
    modules = (CLI, *[m for m in args.module if m != CLI])
    result = census(Path(args.root).resolve(), args.at, sections, modules=modules)
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
