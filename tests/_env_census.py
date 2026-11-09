"""Read where a test or a bench builds a child's environment without a named
variable, for the censuses that need a child to keep one.

Three variables a child must keep, each with its own census:
``ESPALIER_AUDIT_DIR`` (the per-test audit store,
``tests/test_audit_dir_home_unset.py``), ``ESPALIER_PARENT_BASETEMP`` (a
launched pytest nests its temp dirs in its parent's, ``tests/_nested_temp.py``)
and ``PYTEST_CURRENT_TEST`` (a launched pytest skips the session-start temp
sweep, ``tests/_temp_sweep.py``); the last two are read by
``tests/test_proof_tier.py::TestALaunchedChildKeepsItsTempRules``. Each census
names the variable and the names whose store keeps the child's run right
without it (a store of its own, or a home or temp root of the child's own).

A ``startswith`` filter is read for the variable itself, so a strip of
``ESPALIER_`` drops ``ESPALIER_PARENT_BASETEMP`` and passes
``PYTEST_CURRENT_TEST``, and a strip of ``PYTEST_`` the other way round.
"""
from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    parent: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[id(child)] = node
    return parent


def drops(text: str, key: str, keeping: Iterable[str]) -> list[int]:
    """The lines where ``text`` builds a child's env without ``key`` and
    stores none of ``keeping`` in its place: a comprehension whose
    ``startswith`` filter names a prefix of ``key`` (a string or a tuple, any
    quoting; a prefix at least as long as the key's first word), or a
    ``pop``/``del`` of the name. A dict comprehension inside a function keeps
    the variable when its filter, run on the name itself, selects it; one at
    module level never does, since it is built at import, before a test's own
    value exists. Any site passes whose function (the module, for a
    module-level one) stores one of ``keeping`` as a subscript, a dict key, a
    keyword, or the first argument of a ``setenv`` call (pytest's
    ``monkeypatch.setenv``). A filter that reads another name is not run, and its site
    counts as dropping. Not read: a loop of ``if`` statements popping by
    prefix, a prefix held in a named constant, and a child script inside a
    string."""
    keeping = frozenset(keeping)
    floor = len(key.split("_", 1)[0])
    tree = ast.parse(text)
    parent = _parents(tree)

    def ancestors(node: ast.AST) -> Iterator[ast.AST]:
        while id(node) in parent:
            node = parent[id(node)]
            yield node

    def scope(node: ast.AST) -> ast.AST:
        return next((a for a in ancestors(node)
                     if isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))), tree)

    def stores(where: ast.AST) -> bool:
        for n in ast.walk(where):
            if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store) \
                    and isinstance(n.slice, ast.Constant) and n.slice.value in keeping:
                return True
            if isinstance(n, ast.Dict) and any(isinstance(k, ast.Constant) and k.value in keeping
                                               for k in n.keys):
                return True
            if isinstance(n, ast.keyword) and n.arg in keeping:
                return True
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "setenv" and n.args \
                    and isinstance(n.args[0], ast.Constant) and n.args[0].value in keeping:
                return True
        return False

    def names_the_key(call: ast.Call) -> bool:
        if getattr(call.func, "attr", None) != "startswith" or not call.args:
            return False
        arg = call.args[0]
        return any(isinstance(p, ast.Constant) and isinstance(p.value, str) and len(p.value) >= floor
                   and key.startswith(p.value)
                   for p in (arg.elts if isinstance(arg, ast.Tuple) else [arg]))

    def filter_keeps(comp: ast.DictComp) -> bool:
        if len(comp.generators) != 1:
            return False
        gen = comp.generators[0]
        name = ast.Constant(key)
        items = isinstance(gen.iter, ast.Call) and getattr(gen.iter.func, "attr", None) == "items"
        item = ast.Tuple([name, ast.Constant("x")], ast.Load()) if items else name
        run = ast.Expression(ast.ListComp(ast.Constant(1), [
            ast.comprehension(gen.target, ast.List([item], ast.Load()), gen.ifs, 0)]))
        try:
            return bool(eval(compile(ast.fix_missing_locations(run), "<filter>", "eval"), {"__builtins__": {}}))
        except Exception:  # a filter that reads another name is not run: the site counts as dropping
            return False

    comps = (ast.DictComp, ast.ListComp, ast.SetComp, ast.GeneratorExp)
    found = set()
    for node in ast.walk(tree):
        if any(isinstance(a, ast.Assert) for a in ancestors(node)):
            continue
        if isinstance(node, ast.Call) and names_the_key(node):
            comp = next((a for a in ancestors(node) if isinstance(a, comps)), None)
            if comp is None:
                continue  # one name tested, not an env built by a filter
            where = scope(comp)
            if isinstance(comp, ast.DictComp) and where is not tree and filter_keeps(comp):
                continue
            if not stores(where):
                found.add(comp.lineno)
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "pop" and node.args \
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == key:
            if not stores(scope(node)):
                found.add(node.lineno)
        elif isinstance(node, ast.Delete):
            if any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                   and t.slice.value == key for t in node.targets) and not stores(scope(node)):
                found.add(node.lineno)
    return sorted(found)
