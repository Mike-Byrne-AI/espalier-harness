"""TP-169 §13 #7 — Class-B: malformed/non-dict JSON fail-open closure.

Three layers:

1. ``TestLoadJsonDictSafe`` — unit-tests the chokepoint
   ``tools/cc/_json_safe.load_json_dict_safe`` against every bad input shape.
2. ``TestNoJsonFailOpenInToolsCc`` — the CLASS-CLOSING gate. AST-walks all of
   ``tools/cc`` and FAILS on any ``json.loads``/``json.load`` whose result is
   dict-dereferenced (``.get``/``[..]``/``.items``/``.keys``/``.values``/
   ``.setdefault``) or escapes via ``return`` WITHOUT an ``isinstance(x, dict)``
   guard on the way to that deref (its own path -- DEF-833; a guard anywhere in
   the function greened every deref once one branch type-checked the name) and
   not routed through the chokepoint. This is the regression test that closes
   the whole class, not the ~13 instances.
3. ``TestGateEarnsRed`` — gate-credibility (TP-105 "earn the gate"): the gate
   MUST flag a synthetic fail-open and MUST pass a guarded twin, so it can
   never silently degrade to a no-op.

Plus ``TestN4RepoNameFailOpen`` — the highest-severity behavior regression
(a non-dict ``package.json`` must NOT crash SessionStart / PostCompact).
"""
from __future__ import annotations

import ast
import importlib.util
import tokenize
from pathlib import Path

import pytest

from _site_path import site_path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_CC = REPO_ROOT / "tools" / "cc"
# TP-169 §13 #8 round-4 (Survivor B): the Class-B gate originally walked only
# tools/cc/ — but espalier/ carries the same `json.loads(...).get(...)` fail-open
# class (round-3 itself hand-patched espalier/ sites). The gate now walks BOTH.
# espalier/ cannot import the tools/cc chokepoint (isolation rule), so its sites
# satisfy the gate via inline `isinstance(x, dict)` guards or the pragma.
ESPALIER = REPO_ROOT / "espalier"
_GATE_ROOTS = (TOOLS_CC, ESPALIER)

# ── load the chokepoint under test ───────────────────────────────────────────


def _load_json_safe():
    spec = importlib.util.spec_from_file_location(
        "_tp169_json_safe", TOOLS_CC / "_json_safe.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


load_json_dict_safe = _load_json_safe().load_json_dict_safe


# ── the gate's AST classifier (also exercised by TestGateEarnsRed) ───────────

# Dict-only methods (.update/.setdefault never exist on list) plus the shared
# ones (.get/.items/.keys/.values/.pop) — a json-sourced name reached by any of
# these is being treated as a dict, so it must be isinstance-guarded first.
DICT_DEREF_ATTRS = {"get", "items", "keys", "values", "setdefault", "pop", "update"}
# Container methods that ingest a parsed element (the §1.10/TP-170 "append-then-
# element-deref" shape: the parse result is neither directly dereffed nor bound
# to a Name, so the per-call and alias passes both miss it).
_COLLECT_METHODS = {"append", "add", "insert", "extend"}
PRAGMA = "json-dict-safe: ok"
# The chokepoint module is itself the safe home for json.loads.
EXEMPT_FILES = {"_json_safe.py"}


def _json_module_aliases(tree: ast.AST) -> set[str]:
    """Names that refer to the json module: `json`, any `import json as j`, and
    any `j = importlib.import_module("json")` / `import_module("json")` binding.

    TP-170: the dynamic-import shape is invisible to a static `import json`
    scan, so `j = import_module("json"); j.loads(s).get(...)` would have
    slipped past the gate (latent — no in-repo instance, closed pre-emptively
    like the §13.7 R1 alias/ternary hardening)."""
    names = {"json"}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name == "json" and a.asname:
                    names.add(a.asname)
        elif (
            isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
            and isinstance(n.value, ast.Call)
            and len(n.value.args) == 1
            and isinstance(n.value.args[0], ast.Constant)
            and n.value.args[0].value == "json"
            and (
                (isinstance(n.value.func, ast.Attribute) and n.value.func.attr == "import_module")
                or (isinstance(n.value.func, ast.Name) and n.value.func.id == "import_module")
            )
        ):
            names.add(n.targets[0].id)
    return names


def _is_json_load(node: ast.AST, names: set[str] = frozenset({"json"})) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (
        isinstance(f, ast.Attribute)
        and f.attr in ("loads", "load")
        and isinstance(f.value, ast.Name)
        and f.value.id in names
    )


def _bare_json_aliases(tree: ast.AST) -> list[str]:
    """`from json import loads/load` would defeat attribute matching."""
    hits: list[str] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "json":
            for a in n.names:
                if a.name in ("loads", "load"):
                    hits.append(a.asname or a.name)
    return hits


def _pragma_lines(src: str) -> set[int]:
    lines: set[int] = set()
    try:
        reader = iter(src.splitlines(keepends=True))
        for tok in tokenize.generate_tokens(lambda: next(reader, "")):
            if tok.type == tokenize.COMMENT and PRAGMA in tok.string:
                lines.add(tok.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return lines


def _parents(tree: ast.AST) -> dict:
    out: dict = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[child] = node
    return out


def _enclosing(node, parents, types):
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, types):
            return cur
        cur = parents.get(cur)
    return None


def _dict_guarded_names_over(nodes) -> set[str]:
    """The names an ``isinstance(x, dict)`` check (or a tuple holding ``dict``)
    names among ``nodes`` -- the nodes on ONE site's path (DEF-833), never a
    whole function: a guard anywhere in the function greened every deref in
    it once one branch type-checked the name."""
    names: set[str] = set()
    for n in nodes:
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "isinstance"
            and len(n.args) == 2
            and isinstance(n.args[0], ast.Name)
        ):
            second = n.args[1]
            if (isinstance(second, ast.Name) and second.id == "dict") or (
                isinstance(second, ast.Tuple)
                and any(isinstance(e, ast.Name) and e.id == "dict" for e in second.elts)
            ):
                names.add(n.args[0].id)
    return names


def _guarded_on_the_path(fn: ast.AST, site: ast.AST, name: str) -> bool:
    """``name`` is dict-guarded on the way to ``site``: a check on the path
    names it, or names a name it aliases along the path (``b = a`` with
    ``a`` checked: the alias inherits the guard, as before). The path is
    ``tests/_site_path.py``'s -- the statements before the site in its block
    and in each enclosing block, a preceding branch that returns pruned, the
    enclosing headers (a guard written as the ``if`` around the deref), and
    the site's statement whole; block-prefix, not control flow. A site the
    walk cannot place (a default argument, a decorator) reads as unguarded."""
    try:
        nodes = site_path(fn, site).nodes()
    except ValueError:
        return False
    guarded = _dict_guarded_names_over(nodes)
    aliases = [
        (n.targets[0].id, n.value.id)
        for n in nodes
        if isinstance(n, ast.Assign) and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Name)
    ]
    changed = True
    while changed:  # fixpoint over Name = Name aliases on the path
        changed = False
        for tgt, val in aliases:
            if val in guarded and tgt not in guarded:
                guarded.add(tgt)
                changed = True
    return name in guarded


def _deref_sites(fn: ast.AST, name: str) -> list[ast.AST]:
    """Every dict-deref of ``name`` under ``fn``: ``name.get(...)`` and its
    siblings in ``DICT_DEREF_ATTRS``, and ``name[...]``."""
    out: list[ast.AST] = []
    for n in ast.walk(fn):
        if (
            isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id == name
            and n.attr in DICT_DEREF_ATTRS
        ):
            out.append(n)
        elif isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == name:
            out.append(n)
    return out


def _name_dict_dereffed(fn: ast.AST, name: str) -> bool:
    return bool(_deref_sites(fn, name))


def _subtree_has_name(node, name: str) -> bool:
    if node is None:
        return False
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node))


def _returned_raw(ret: ast.Return, is_it) -> bool:
    """``ret`` hands a node ``is_it`` accepts back to the caller raw: as the
    value, or inside a container, a conditional or a boolean in it. An
    argument to a call in the value (``return helper(existing=d)``,
    ``return helper(json.loads(s))``) is not that: it is the pass to a
    consumer the census does not follow, exactly as ``helper(d)`` on its own
    line is, and the loader-return shape this flags is the raw parse
    reaching the caller. One rule for the parse itself and for a name bound
    to it, so hoisting the parse to a local cannot change the verdict.
    (Measured 2026-09-17 when the guard moved onto the path: one live site,
    the settings reconciler's ``--wire-hooks`` return, was flagged by the
    argument reading alone; the function-wide proxy had greened it by a
    guard in a later branch.)"""
    if ret.value is None:
        return False
    parents = _parents(ret.value)
    for n in ast.walk(ret.value):
        if not is_it(n):
            continue
        cur: ast.AST = n
        passed = False
        while cur is not ret.value and cur in parents:
            parent = parents[cur]
            if isinstance(parent, ast.Call) and any(a is cur for a in parent.args):
                passed = True
                break
            if isinstance(parent, ast.keyword):
                passed = True
                break
            cur = parent
        if not passed:
            return True
    return False


def _returns_raw(ret: ast.Return, name: str) -> bool:
    return _returned_raw(ret, lambda n: isinstance(n, ast.Name) and n.id == name)


def _escape_sites(fn: ast.AST, name: str) -> list[ast.Return]:
    """Every ``return`` under ``fn`` that hands ``name`` back raw."""
    return [n for n in ast.walk(fn) if isinstance(n, ast.Return) and _returns_raw(n, name)]


def _unguarded_use(fn: ast.AST, name: str) -> str | None:
    """How ``name`` first reaches a consumer with no dict guard on the way to
    it (DEF-833): ``"dict-dereffed"`` for a deref, ``"returned/escapes"`` for
    a ``return`` carrying it; ``None`` when every use is guarded on its own
    path. Each site is judged on its path, never on the function: two derefs
    with one guard in one arm is the row this exists to flag."""
    for site in _deref_sites(fn, name):
        if not _guarded_on_the_path(fn, site, name):
            return "dict-dereffed"
    for site in _escape_sites(fn, name):
        if not _guarded_on_the_path(fn, site, name):
            return "returned/escapes"
    return None


def find_json_fail_opens(src: str, label: str = "<src>") -> list[str]:
    """Return human-readable findings; empty list means compliant."""
    tree = ast.parse(src)
    parents = _parents(tree)
    names = _json_module_aliases(tree)
    findings: list[str] = []
    for alias in _bare_json_aliases(tree):
        findings.append(f"{label}: `from json import {alias}` defeats the gate's attribute match")
    prag = _pragma_lines(src)
    seen: set[int] = set()
    for node in ast.walk(tree):
        if not _is_json_load(node, names) or node.lineno in prag or node.lineno in seen:
            continue
        fn = _enclosing(node, parents, (ast.FunctionDef, ast.AsyncFunctionDef))
        stmt = _enclosing(node, parents, ast.stmt)
        shape = _classify(node, stmt, fn, parents)
        if shape:
            seen.add(node.lineno)
            findings.append(f"{label}:{node.lineno}: {shape}")
    # Transitive alias pass: catch `a = json.loads(s); b = a; b.get(...)` where
    # the ORIGINAL name is never dereffed (so the per-call loop above misses it)
    # but a renamed alias is. Honest-drift, not just adversarial.
    for line, shape in _alias_fail_opens(tree, prag, seen, names):
        findings.append(f"{label}:{line}: {shape}")
    # Collection pass: catch `X.append(json.load(...))` then an ELEMENT of X
    # dict-dereffed (loop var / sort|sorted key lambda / X[i].get / comprehension).
    # The parse is neither directly dereffed nor bound to a Name, so the two
    # passes above miss it (TP-170 — the real in-repo instance was the
    # scaffolding_canon blueprint loader).
    for line, shape in _collection_fail_opens(tree, prag, seen, names):
        findings.append(f"{label}:{line}: {shape}")
    return findings


def _key_lambda(call: ast.Call) -> ast.Lambda | None:
    for kw in call.keywords:
        if kw.arg == "key" and isinstance(kw.value, ast.Lambda):
            return kw.value
    return None


def _subscript_of(node, container: str) -> bool:
    """True if ``node`` is ``container[...]`` (a Subscript on the container Name)."""
    return isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == container


def _element_dereffed(fn: ast.AST, container: str) -> bool:
    """True if an ELEMENT of ``container`` (a Name) is dict-dereffed in ``fn``
    with no guard on the way to that deref: via a ``for v in container`` loop
    var, a ``container.sort(key=lambda v: …)`` / ``sorted|min|max(container,
    key=lambda v: …)`` element arg, a comprehension ``for v in container``
    (each element variable's deref judged on its own path, DEF-833: an
    ``isinstance(v, dict)`` on the way to it clears it), or a direct
    ``container[i].<deref>`` / ``container[i][…]`` (no name a guard could
    carry, so it always counts)."""
    elem_vars: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, (ast.For, ast.comprehension)):
            if isinstance(n.iter, ast.Name) and n.iter.id == container and isinstance(n.target, ast.Name):
                elem_vars.add(n.target.id)
        elif isinstance(n, ast.Call):
            lam = None
            if (
                isinstance(n.func, ast.Attribute) and n.func.attr == "sort"
                and isinstance(n.func.value, ast.Name) and n.func.value.id == container
            ):
                lam = _key_lambda(n)
            elif (
                isinstance(n.func, ast.Name) and n.func.id in ("sorted", "min", "max")
                and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id == container
            ):
                lam = _key_lambda(n)
            if lam is not None and lam.args.args:
                elem_vars.add(lam.args.args[0].arg)
        elif isinstance(n, ast.Attribute) and n.attr in DICT_DEREF_ATTRS and _subscript_of(n.value, container):
            return True  # container[i].get(...)
        elif isinstance(n, ast.Subscript) and _subscript_of(n.value, container):
            return True  # container[i][...]
    return any(not _guarded_on_the_path(fn, site, v) for v in elem_vars for site in _deref_sites(fn, v))


def _collection_fail_opens(tree, prag, already_flagged, names):
    """Flag a json parse COLLECTED into a container (``X.append(json.load(...))``,
    ``.add``/``.insert``/``.extend``) whose ELEMENTS are later dict-dereffed
    without an ``isinstance(elem, dict)`` guard on the way to the element's
    deref (a direct ``container[i]`` deref has no name a guard could carry,
    and always counts)."""
    out: list[tuple[int, str]] = []
    for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
        collected: dict[str, int] = {}  # container Name -> json parse lineno
        for n in ast.walk(fn):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr in _COLLECT_METHODS
                and isinstance(n.func.value, ast.Name)
            ):
                for arg in n.args:
                    for c in ast.walk(arg):
                        if _is_json_load(c, names) and c.lineno not in prag and c.lineno not in already_flagged:
                            collected.setdefault(n.func.value.id, c.lineno)
        for container, line in collected.items():
            if line in already_flagged:
                continue
            if _element_dereffed(fn, container):
                already_flagged.add(line)
                out.append((
                    line,
                    f"COLLECT `{container}.{{append,extend,…}}(json.load(...))` then an element is "
                    f"dict-dereffed, no isinstance(elem, dict) — route the element through "
                    f"load_json_dict_safe or guard it",
                ))
    return out


def _alias_fail_opens(tree, prag, already_flagged, names):
    """Flag json-sourced names (incl. transitive ``B = A`` aliases) that are
    dict-dereffed or escape via return without an isinstance(x, dict) guard on
    the way to that use, when the per-call pass did not already flag that
    parse line."""
    out: list[tuple[int, str]] = []
    for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
        sourced: dict[str, int] = {}
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                for c in ast.walk(n.value):
                    if _is_json_load(c, names) and c.lineno not in prag:
                        sourced[n.targets[0].id] = c.lineno
        if not sourced:
            continue
        changed = True
        while changed:  # fixpoint over Name = Name aliases (the source propagates; the guard is judged per site)
            changed = False
            for n in ast.walk(fn):
                if not (
                    isinstance(n, ast.Assign)
                    and len(n.targets) == 1
                    and isinstance(n.targets[0], ast.Name)
                    and isinstance(n.value, ast.Name)
                ):
                    continue
                tgt, val = n.targets[0].id, n.value.id
                if val in sourced and tgt not in sourced:
                    sourced[tgt] = sourced[val]
                    changed = True
        for name, line in sourced.items():
            if line in already_flagged:
                continue
            use = _unguarded_use(fn, name)
            if use:
                already_flagged.add(line)
                out.append((line, f"ALIAS `{name}` of a json parse {use}, no isinstance({name}, dict) on the way to it"))
    return out


def _classify(call, stmt, fn, parents) -> str | None:
    # Direct deref: json.loads(...).get(...) / json.loads(...)[...]
    parent = parents.get(call)
    # Walrus: `(d := json.loads(s)).get(...)` or `if (d := json.loads(s)):` then
    # `d` dict-dereffed. The parse's parent is a NamedExpr, so the Attribute/
    # Subscript checks below see the NamedExpr, not the call — handle it here.
    # (TP-170 latent gate gap — no in-repo instance, closed pre-emptively.)
    if isinstance(parent, ast.NamedExpr) and parent.value is call:
        gp = parents.get(parent)
        if isinstance(gp, ast.Attribute) and gp.attr in DICT_DEREF_ATTRS:
            return f"WALRUS (… := json.load(...)).{gp.attr}(...) — no guard"
        if isinstance(gp, ast.Subscript) and gp.value is parent:
            return "WALRUS (… := json.load(...))[...] — no guard"
        tgt = parent.target.id if isinstance(parent.target, ast.Name) else None
        if tgt is not None and fn is not None:
            use = _unguarded_use(fn, tgt)
            if use:
                return f"WALRUS `{tgt} := …json…` {use}, no isinstance({tgt}, dict) on the way to it"
        return None
    if isinstance(parent, ast.Attribute) and parent.attr in DICT_DEREF_ATTRS:
        return f"DIRECT json.loads(...).{parent.attr}(...) — no guard"
    if isinstance(parent, ast.Subscript) and parent.value is call:
        return "DIRECT json.loads(...)[...] — no guard"
    # Escape via return: the parse handed back raw (bare, in a container, a
    # conditional or a boolean). As a call argument it is a pass -- the same
    # rule `_returned_raw` reads for a name bound to it, so the direct and
    # the bound spelling of one pass agree.
    if isinstance(stmt, ast.Return) and _returned_raw(stmt, lambda n: n is call):
        return "ESCAPE — json parse in `return ...` (loader returns raw, callers deref)"
    # Assignment: track the bound name, flag if dict-dereffed/returned unguarded.
    target_name = None
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
        target_name = stmt.targets[0].id
    elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        target_name = stmt.target.id
    if target_name is not None and stmt.value is not None and any(n is call for n in ast.walk(stmt.value)):
        if fn is None:
            return None
        use = _unguarded_use(fn, target_name)
        if use:
            return f"ASSIGN `{target_name} = ...json...` {use}, no isinstance({target_name}, dict) on the way to it"
        return None  # Name target: every deref/return guarded on its own path, or none at all → safe
    # Assigned to a target the name-based model can't track (tuple-unpack,
    # attribute, subscript, or chained `a = b = ...`): a guard on such a target
    # is invisible to the gate, so treat the parse as unguarded (R1 hardening —
    # latent gate gaps surfaced by the §13.7 adversarial pass).
    if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None and any(n is call for n in ast.walk(stmt.value)):
        return ("ASSIGN to a non-Name target (tuple/attribute/subscript/chained) — gate "
                "cannot verify a dict guard; route through load_json_dict_safe or add a pragma")
    return None


# ── 1. chokepoint unit tests ─────────────────────────────────────────────────


class TestLoadJsonDictSafe:
    def test_dict_passes_through(self):
        assert load_json_dict_safe('{"a": 1}') == {"a": 1}

    @pytest.mark.parametrize("payload", ["[]", "[1,2]", '"str"', "42", "3.5", "null", "true"])
    def test_valid_json_non_dict_returns_default(self, payload):
        assert load_json_dict_safe(payload) == {}

    @pytest.mark.parametrize("payload", ["", "{", "not json", "{'a': 1}", "\x00\xff"])
    def test_malformed_returns_default(self, payload):
        assert load_json_dict_safe(payload) == {}

    def test_custom_default_none(self):
        assert load_json_dict_safe("[]", default=None) is None
        assert load_json_dict_safe("nope", default=None) is None
        assert load_json_dict_safe('{"x":1}', default=None) == {"x": 1}

    def test_custom_default_value(self):
        sentinel = {"fallback": True}
        assert load_json_dict_safe("[]", default=sentinel) is sentinel

    def test_non_str_input(self):
        assert load_json_dict_safe(None) == {}
        assert load_json_dict_safe(123) == {}
        assert load_json_dict_safe(["already", "parsed"]) == {}

    def test_bytes_input_with_bom(self):
        assert load_json_dict_safe(b"\xef\xbb\xbf{\"a\": 1}") == {"a": 1}
        assert load_json_dict_safe(b'{"a": 1}') == {"a": 1}

    def test_bytearray_and_bad_utf8(self):
        assert load_json_dict_safe(bytearray(b'{"a": 1}')) == {"a": 1}
        # lone surrogate / invalid UTF-8 must not raise (utf-8-sig + replace)
        assert load_json_dict_safe(b"\xed\xa0\x80") == {}

    def test_deep_nesting_never_raises(self):
        # A JSON bomb (deep nesting) must collapse to default, never escape as
        # RecursionError. CPython's C scanner is iterative; this also covers the
        # pure-Python fallback via the RecursionError catch.
        assert load_json_dict_safe("[" * 50000 + "]" * 50000) == {}
        assert isinstance(load_json_dict_safe('{"a":' * 40000 + "1" + "}" * 40000), dict)

    def test_default_is_fresh_each_call(self):
        a = load_json_dict_safe("[]")
        b = load_json_dict_safe("[]")
        a["mutated"] = True
        assert b == {}, "unspecified default must be a fresh dict per call, not shared"


# ── 2. the class-closing gate ────────────────────────────────────────────────


def _iter_guarded_py():
    for root in _GATE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if "test" in path.name or path.name in EXEMPT_FILES:
                continue
            yield path


class TestNoJsonFailOpenInGoverningCode:
    def test_no_unguarded_json_dict_deref(self):
        offenders: list[str] = []
        for path in _iter_guarded_py():
            rel = path.relative_to(REPO_ROOT).as_posix()
            offenders.extend(find_json_fail_opens(path.read_text(encoding="utf-8"), rel))
        assert not offenders, (
            "Class-B fail-open(s) in tools/cc/ or espalier/ — route through "
            "tools/cc/_json_safe.load_json_dict_safe (tools/cc only) or add an "
            "`isinstance(x, dict)` guard (or a `# json-dict-safe: ok <reason>` "
            "pragma for a deliberately non-dict parse):\n  " + "\n  ".join(offenders)
        )

    def test_chokepoint_module_exists(self):
        assert (TOOLS_CC / "_json_safe.py").is_file()


# ── 3. gate credibility (earn the gate) ──────────────────────────────────────


class TestGateEarnsRed:
    def test_flags_assign_then_deref(self):
        src = (
            "import json\n"
            "def f(s):\n"
            "    data = json.loads(s)\n"
            "    return data.get('x')\n"
        )
        assert find_json_fail_opens(src), "gate must flag assign-then-deref"

    def test_flags_loader_return(self):
        src = "import json\ndef f(p):\n    return json.loads(p.read_text())\n"
        assert find_json_fail_opens(src), "gate must flag a loader returning raw json"

    def test_flags_direct_deref(self):
        src = "import json\ndef f(s):\n    return json.loads(s).get('x')\n"
        assert find_json_fail_opens(src), "gate must flag json.loads(...).get(...)"

    def test_flags_ternary_assign(self):
        src = (
            "import json\n"
            "def f(a, b):\n"
            "    r = json.loads(a) if a else json.loads(b)\n"
            "    return r.get('x')\n"
        )
        assert find_json_fail_opens(src), "gate must see json.loads nested in a ternary assign"

    def test_flags_bare_import_alias(self):
        src = "from json import loads\ndef f(s):\n    return loads(s).get('x')\n"
        assert find_json_fail_opens(src), "gate must flag `from json import loads`"

    def test_flags_rename_alias_deref(self):
        # honest-drift: parse bound to `a`, renamed to `b`, then `b` dereffed
        src = (
            "import json\n"
            "def f(s):\n"
            "    a = json.loads(s)\n"
            "    b = a\n"
            "    return b.get('x')\n"
        )
        assert find_json_fail_opens(src), "gate must follow B = A alias of a json parse"

    def test_flags_module_alias_import(self):
        # `import json as j` then j.loads must still be seen (TP-169 §13 #7 R1)
        src = "import json as j\ndef f(s):\n    d = j.loads(s)\n    return d.get('x')\n"
        assert find_json_fail_opens(src), "gate must follow `import json as j`"

    @pytest.mark.parametrize("method", ["pop", "update", "setdefault"])
    def test_flags_dict_mutator_deref(self, method):
        src = f"import json\ndef f(s):\n    d = json.loads(s)\n    d.{method}('x')\n    return d\n"
        assert find_json_fail_opens(src), f"gate must flag a json parse reached via .{method}"

    def test_flags_tuple_unpack_target(self):
        src = "import json\ndef f(s):\n    d, _ = json.loads(s), 0\n    return d.get('x')\n"
        assert find_json_fail_opens(src), "gate must flag a json parse assigned to a tuple target"

    def test_flags_attribute_target(self):
        src = "import json\nclass C:\n    def f(self, s):\n        self.d = json.loads(s)\n        return self.d.get('x')\n"
        assert find_json_fail_opens(src), "gate must flag a json parse assigned to an attribute target"

    # ── TP-170: indirect-deref shapes the §13.7 gate missed ──────────────────
    def test_flags_append_then_sort_key_deref(self):
        # The real in-repo instance (scaffolding_canon blueprint loader): parse
        # appended into a list, then a sort-key lambda dereffes each element.
        src = (
            "import json\n"
            "def f(files):\n"
            "    out = []\n"
            "    for p in files:\n"
            "        out.append(json.load(p))\n"
            "    out.sort(key=lambda d: d.get('depth', 0))\n"
            "    return out\n"
        )
        assert find_json_fail_opens(src), "gate must flag append-then-sort-key element deref"

    def test_flags_append_then_loop_deref(self):
        src = (
            "import json\n"
            "def f(files):\n"
            "    out = []\n"
            "    for p in files:\n"
            "        out.append(json.load(p))\n"
            "    for d in out:\n"
            "        print(d.get('x'))\n"
        )
        assert find_json_fail_opens(src), "gate must flag append-then-loop element deref"

    def test_flags_append_then_index_deref(self):
        src = (
            "import json\n"
            "def f(files):\n"
            "    out = []\n"
            "    for p in files:\n"
            "        out.append(json.load(p))\n"
            "    return out[0].get('x')\n"
        )
        assert find_json_fail_opens(src), "gate must flag append-then-subscript element deref"

    def test_flags_walrus_direct_deref(self):
        src = "import json\ndef f(s):\n    return (d := json.loads(s)).get('x')\n"
        assert find_json_fail_opens(src), "gate must flag a walrus-bound parse dereffed"

    def test_flags_walrus_then_deref(self):
        src = (
            "import json\n"
            "def f(s):\n"
            "    if (d := json.loads(s)):\n"
            "        return d.get('x')\n"
        )
        assert find_json_fail_opens(src), "gate must flag a walrus-bound name later dereffed"

    def test_flags_import_module_alias(self):
        src = (
            "import importlib\n"
            "def f(s):\n"
            "    j = importlib.import_module('json')\n"
            "    return j.loads(s).get('x')\n"
        )
        assert find_json_fail_opens(src), "gate must follow `import_module('json')` aliases"

    def test_passes_append_with_guarded_element(self):
        # element guarded before deref → safe
        src = (
            "import json\n"
            "def f(files):\n"
            "    out = []\n"
            "    for p in files:\n"
            "        d = json.load(p)\n"
            "        if isinstance(d, dict):\n"
            "            out.append(d)\n"
            "    return out[0].get('x')\n"
        )
        assert not find_json_fail_opens(src), "an element guarded with isinstance(d, dict) must pass"

    def test_passes_unused_assign(self):
        # a single-Name parse that is never dict-dereffed/returned is safe
        src = "import json\ndef f(s):\n    d = json.loads(s)\n    return 1\n"
        assert not find_json_fail_opens(src), "an unused json parse must not be flagged"

    def test_passes_isinstance_guarded(self):
        src = (
            "import json\n"
            "def f(s):\n"
            "    data = json.loads(s)\n"
            "    if not isinstance(data, dict):\n"
            "        return None\n"
            "    return data.get('x')\n"
        )
        assert not find_json_fail_opens(src), "isinstance(x, dict) guard must satisfy the gate"

    def test_passes_inline_isinstance(self):
        src = (
            "import json\n"
            "def f(s):\n"
            "    data = json.loads(s)\n"
            "    return data.get('x') if isinstance(data, dict) else None\n"
        )
        assert not find_json_fail_opens(src)

    def test_passes_pragma(self):
        src = (
            "import json\n"
            "def f(line):\n"
            "    rec = json.loads(line)  # json-dict-safe: ok — JSONL, guarded below\n"
            "    return rec\n"
        )
        assert not find_json_fail_opens(src), "pragma must exempt a deliberately non-dict parse"

    def test_passes_chokepoint_call(self):
        src = (
            "from _json_safe import load_json_dict_safe\n"
            "def f(s):\n"
            "    return load_json_dict_safe(s).get('x')\n"
        )
        assert not find_json_fail_opens(src), "routing through the chokepoint must satisfy the gate"


class TestTheGuardIsKeyedOnTheDerefsPath:
    """DEF-833: a guard is credited to a deref (or a return escape) only when
    it runs on the way to it -- the statements before it in its own block and
    in each enclosing block, a preceding branch that returns pruned, plus the
    headers of the compound statements around it (``tests/_site_path.py``).
    The function-wide proxy greened every deref once one branch type-checked
    the name; the two-sites-one-guard rows are the must-red twins the shape
    needs (``docs/FAILURE_MODES.md`` 18.15). The rule is block-prefix, not
    control flow: a guard under a condition above the deref is accepted."""

    MUST_FLAG = [
        (
            "a-second-deref-whose-guard-sits-in-a-sibling-arm-that-returns",
            "import json\n"
            "def f(s, flag):\n"
            "    d = json.loads(s)\n"
            "    if flag:\n"
            "        if isinstance(d, dict):\n"
            "            return d.get('a')\n"
            "        return None\n"
            "    return d['b']\n",
        ),
        (
            "a-guard-textually-after-the-deref",
            "import json\n"
            "def f(s):\n"
            "    d = json.loads(s)\n"
            "    x = d.get('a')\n"
            "    if isinstance(d, dict):\n"
            "        return x\n"
            "    return None\n",
        ),
        (
            "an-escape-whose-guard-sits-in-an-arm-that-returns",
            "import json\n"
            "def f(s, flag):\n"
            "    d = json.loads(s)\n"
            "    if flag:\n"
            "        if isinstance(d, dict):\n"
            "            return d\n"
            "        return None\n"
            "    return d\n",
        ),
        (
            "an-alias-whose-guard-sits-in-an-arm-that-returns",
            "import json\n"
            "def f(s, flag):\n"
            "    a = json.loads(s)\n"
            "    b = a\n"
            "    if flag:\n"
            "        if isinstance(b, dict):\n"
            "            return b.get('a')\n"
            "        return None\n"
            "    return b['c']\n",
        ),
        (
            "a-walrus-name-dereffed-past-the-arm-that-guards-it",
            "import json\n"
            "def f(s, flag):\n"
            "    if (d := json.loads(s)):\n"
            "        if flag:\n"
            "            if isinstance(d, dict):\n"
            "                return d.get('a')\n"
            "            return None\n"
            "        return d['b']\n",
        ),
        (
            "a-guard-inside-a-lambda-that-never-runs",
            "import json\n"
            "def f(s):\n"
            "    d = json.loads(s)\n"
            "    ok = lambda: isinstance(d, dict)\n"
            "    return d.get('a')\n",
        ),
        (
            "a-guard-inside-a-nested-def-that-never-runs",
            "import json\n"
            "def f(s):\n"
            "    d = json.loads(s)\n"
            "    def chk():\n"
            "        ok = isinstance(d, dict)\n"
            "    return d.get('a')\n",
        ),
        (
            "a-collected-element-dereffed-before-the-loop-that-guards-it",
            "import json\n"
            "def f(files):\n"
            "    out = []\n"
            "    for p in files:\n"
            "        out.append(json.load(p))\n"
            "    for d in out:\n"
            "        print(d.get('y'))\n"
            "    for d in out:\n"
            "        if isinstance(d, dict):\n"
            "            print(d.get('x'))\n",
        ),
    ]

    @pytest.mark.parametrize("shape, src", MUST_FLAG, ids=[shape for shape, _ in MUST_FLAG])
    def test_a_deref_its_guard_never_reaches_is_flagged(self, shape, src):
        assert find_json_fail_opens(src), shape

    RAW_RETURNS = [
        (
            "a-parse-returned-inside-a-container",
            "import json\n"
            "def f(s):\n"
            "    d = json.loads(s)\n"
            "    return {'settings': d}\n",
        ),
        (
            "a-parse-returned-through-a-conditional",
            "import json\n"
            "def f(s, flag):\n"
            "    d = json.loads(s)\n"
            "    return d if flag else None\n",
        ),
        (
            "a-parse-returned-inside-a-container-directly",
            "import json\n"
            "def f(s):\n"
            "    return {'settings': json.loads(s)}\n",
        ),
    ]

    @pytest.mark.parametrize("shape, src", RAW_RETURNS, ids=[shape for shape, _ in RAW_RETURNS])
    def test_the_raw_value_returned_is_still_an_escape(self, shape, src):
        # Controls on the narrowed escape rule, not twins: no guard anywhere,
        # the raw value reaches the caller, the census must still say so.
        assert find_json_fail_opens(src), shape

    def test_the_direct_and_the_bound_spelling_of_a_pass_agree(self):
        # Hoisting the parse to a local must not change the verdict: both are
        # the pass to a helper the census does not follow.
        direct = "import json\ndef f(s):\n    return helper(json.loads(s))\n"
        bound = "import json\ndef f(s):\n    d = json.loads(s)\n    return helper(d)\n"
        assert find_json_fail_opens(direct) == find_json_fail_opens(bound) == []

    MUST_PASS = [
        (
            "the-guard-in-the-enclosing-if-header",
            "import json\n"
            "def f(s):\n"
            "    d = json.loads(s)\n"
            "    if isinstance(d, dict):\n"
            "        return d.get('a')\n"
            "    return None\n",
        ),
        (
            "the-guard-in-the-enclosing-while-header",
            "import json\n"
            "def f(s):\n"
            "    d = json.loads(s)\n"
            "    while isinstance(d, dict):\n"
            "        d = d.get('next')\n"
            "    return None\n",
        ),
        (
            "a-guard-under-a-condition-above-the-deref-is-block-prefix-not-control-flow",
            "import json\n"
            "def f(s, flag):\n"
            "    d = json.loads(s)\n"
            "    if flag:\n"
            "        if not isinstance(d, dict):\n"
            "            d = {}\n"
            "    return d.get('a')\n",
        ),
        (
            "a-guard-then-leave-before-a-deref-inside-a-handler",
            "import json\n"
            "def f(s):\n"
            "    d = json.loads(s)\n"
            "    if not isinstance(d, dict):\n"
            "        return None\n"
            "    try:\n"
            "        return d['a']\n"
            "    except KeyError:\n"
            "        return d.get('b')\n",
        ),
        (
            "each-arm-guards-its-own-deref",
            "import json\n"
            "def f(s, flag):\n"
            "    d = json.loads(s)\n"
            "    if flag:\n"
            "        if isinstance(d, dict):\n"
            "            return d.get('a')\n"
            "        return None\n"
            "    if isinstance(d, dict):\n"
            "        return d['b']\n"
            "    return None\n",
        ),
        (
            "an-alias-guarded-on-the-path-to-its-deref",
            "import json\n"
            "def f(s):\n"
            "    a = json.loads(s)\n"
            "    b = a\n"
            "    if not isinstance(b, dict):\n"
            "        return None\n"
            "    return b.get('a')\n",
        ),
        (
            "a-guard-above-a-nested-def-reaches-a-deref-inside-it",
            "import json\n"
            "def f(s):\n"
            "    d = json.loads(s)\n"
            "    if not isinstance(d, dict):\n"
            "        return None\n"
            "    def g():\n"
            "        return d.get('a')\n"
            "    return g\n",
        ),
        (
            "a-guard-in-the-try-body-reaches-a-deref-in-its-else",
            "import json\n"
            "def f(s):\n"
            "    try:\n"
            "        d = json.loads(s)\n"
            "        assert isinstance(d, dict)\n"
            "    except ValueError:\n"
            "        return None\n"
            "    else:\n"
            "        return d.get('a')\n",
        ),
        (
            "a-collected-element-guarded-on-the-path-to-its-deref",
            "import json\n"
            "def f(files):\n"
            "    out = []\n"
            "    for p in files:\n"
            "        out.append(json.load(p))\n"
            "    for d in out:\n"
            "        if isinstance(d, dict):\n"
            "            print(d.get('x'))\n"
            "    return 1\n",
        ),
        (
            "a-parse-handed-to-a-helper-inside-the-return-is-a-pass-not-an-escape",
            # The consumer is the helper, which the census does not follow
            # (its declared limit); the same pass on its own line was never
            # flagged, and the loader-return shape is the raw value reaching
            # the caller. The live instance: the settings reconciler's
            # --wire-hooks return, whose helper takes any top-level value on
            # purpose so a malformed file gets an honest refusal.
            "import json\n"
            "def f(s):\n"
            "    d = json.loads(s)\n"
            "    return helper(existing=d)\n",
        ),
    ]

    @pytest.mark.parametrize("shape, src", MUST_PASS, ids=[shape for shape, _ in MUST_PASS])
    def test_a_deref_its_guard_reaches_passes(self, shape, src):
        assert not find_json_fail_opens(src), (shape, find_json_fail_opens(src))


# ── 4. N4 behavior regression (the SessionStart fail-open) ───────────────────


def _load_hookside(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS_CC / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestN4RepoNameFailOpen:
    """A valid-JSON-but-non-dict package.json must not crash repo-name lookup
    (N4 — pre-fix `data.get` raised AttributeError → hook exit 1 → SessionStart
    / PostCompact context dropped = fail-open)."""

    @pytest.mark.parametrize(
        "name,relpath",
        [
            ("_tp169_session_start", "hooks/session_start.py"),
            ("_tp169_post_compact", "hooks/post_compact.py"),
        ],
    )
    def test_non_dict_package_json_returns_dir_name(self, tmp_path, name, relpath):
        (tmp_path / "package.json").write_text("[]", encoding="utf-8")
        mod = _load_hookside(name, relpath)
        # TP-204c: the per-hook `_repo_name` copies were hoisted to the single
        # owner `_hook_utils.repo_name(root, warn_label=...)`; each hook imports
        # it (asserting `mod.repo_name` here also pins that wiring). must not
        # raise; falls back to the directory name.
        assert mod.repo_name(tmp_path, warn_label="test") == tmp_path.name

    def test_dict_package_json_name_still_read(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "real-pkg"}', encoding="utf-8")
        mod = _load_hookside("_tp169_session_start2", "hooks/session_start.py")
        assert mod.repo_name(tmp_path, warn_label="test") == "real-pkg"


class TestIntegrityNestedFilesNonDict:
    """TP-169 §13 #7 (adversarial round 1, Angle 3): the chokepoint makes the
    TOP-LEVEL integrity manifest a dict, but a non-dict nested `files` key
    (corrupt/poisoned integrity.json) crashed `sorted(recorded.items())`. Must
    now report a verification FAILURE, not crash and not silently report OK."""

    def _ig(self):
        return _load_hookside("_tp169_integrity", "hooks/_integrity.py")

    @pytest.mark.parametrize("files_val", ["[1, 2]", '"x"', "42", "true"])
    def test_non_dict_files_is_not_ok_no_crash(self, tmp_path, files_val):
        ig = self._ig()
        mp = tmp_path / ig.MANIFEST_PATH
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text('{"schema_version": 1, "files": %s}' % files_val, encoding="utf-8")
        ok, mismatched = ig.verify_integrity(tmp_path)
        assert ok is False
        assert any("files_not_object" in m for m in mismatched)

    def test_empty_and_proper_files_still_work(self, tmp_path):
        ig = self._ig()
        mp = tmp_path / ig.MANIFEST_PATH
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text('{"schema_version": 1, "files": {}}', encoding="utf-8")
        ok, mismatched = ig.verify_integrity(tmp_path)
        assert ok is True and mismatched == []
