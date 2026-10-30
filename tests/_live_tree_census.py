"""The census of live-tree enumerations in ``tests/``: one walker, three readers.

``tests/test_utf8_text_io.py::TestLiveTreeWalkRatchet`` holds the ratchet on
it. ``python3 tests/_live_tree_census.py`` from the repository root prints
``True`` while any site is neither routed nor marked or any engine site is
listed (:func:`probe_open`), and ``--list`` prints the work list. It was the
probe of the live-tree walk row, DEF-2013, struck 2026-10-15 when both halves
reached zero; a row that declares a new engine site takes the same line (the
ratchet reds a declared site no live probe reads). One walker for both, so
the ratchet and a probe cannot disagree about what a site is. The third
reader is ``tests/test_marker_taxonomy.py``'s tree-wide sweep census, which
asks :func:`sites_in` for the routed listings too (its ``listings``) and keeps
the walks rooted at the checkout root, so "rooted" means one thing in both.

**What a site is.** A call in a module directly under ``tests/`` (a test file,
``conftest.py`` or a ``_*.py`` helper) that lists the files of THIS checkout
from the filesystem: ``rglob`` / ``glob`` / ``iterdir`` / ``walk`` on a path
rooted in the checkout, ``os.walk`` / ``os.scandir`` / ``os.listdir`` /
``glob.glob`` / ``glob.iglob`` (its ``root_dir=`` too) / ``shutil.copytree`` /
``safe_rglob`` on one, or a call of a scanner's walker (a top-level function of
``espalier/scanners/*.py`` that walks, derived below) with one as its first
argument. A filesystem walk sees what git ignores: a maintainer's untracked
script under the gitignored ``reports/``, ``docs/session-archive.md``, a Windows
copy-duplicate ``docs/X (1).md``, a second checkout under ``.claude/worktrees/``
-- and a contract test then reds on a file no commit carries. Git's view of the
checkout (tracked plus untracked-not-ignored, ``tests/_live_tree.py``) is what
the contracts mean by "this tree".

**Rooted in the checkout** means the path expression resolves, through the
bindings this walker follows, to the repository root or a directory under it:
a name matching ``_ROOT_NAME`` (``REPO_ROOT``, ``ROOT``, ``REPO`` and their
underscore forms); ``Path(__file__)`` / ``pathlib.Path(__file__)`` climbed with
``.parent`` / ``.parents[k]`` (judged from the module's own place, ``tests/``);
``.parent`` / ``.parents[k]`` of a rooted path; ``Path(<a module of this
repository>.__file__)`` (a computed root); a name bound to a rooted expression
in the enclosing function, its class, the module, or a tests module it imports
the name from; a ``for`` / comprehension target over a literal tuple or list of
rooted expressions, or over a name or attribute bound to one; a function
parameter that a call in the same module passes a rooted expression, resolved
in the CALLER's scope (or whose default is one); what a function or method of
the same module returns; ``self.X`` / ``cls.X`` / ``type(self).X`` for a rooted
class attribute; a conditional expression with a rooted branch; and ``/``
joins, ``joinpath``, ``Path(a, b, ...)``, ``str()`` / ``Path()`` /
``os.fspath()``, ``.resolve()`` / ``.absolute()``, ``os.path.join`` and an
f-string over any of these. A join with a string literal names the directory;
any other join is a COMPUTED root (``<computed>`` in the directory).

**Routed** means the site's result goes through git's view: the call is the
first argument of ``keep_in_checkout(...)`` (the filter for a scanner's result)
-- except a scanner in :data:`RAISING_SCANNERS`, whose walk raises before the
filter sees anything. A walk replaced by ``checkout_glob`` / ``checkout_files``
and a copy replaced by ``copy_checkout`` are no longer sites at all.

**Marked** means a ``# live-tree: ok -- <reason>`` comment sits on the call's
own first line or in the block of comment-only lines directly above it: a walk
that must see past git on purpose (a mutation guard snapshotting the tree, a
reader of the gitignored session state itself, which git's view would blind --
``tests/_live_tree.py`` refuses a base git ignores for that reason). The
ratchet names every marked site, so an exemption is a test-file diff a reviewer
reads.

**Not read, and known:** a root reached through a call into another module, a
container the walk indexes, a parameter fed only from another module or a
fixture, ``Path.cwd()`` / ``Path(".")`` (a test's working directory is not
always the root), ``importlib.resources.files``, and ``tests/`` subdirectories
(the fixture trees are planted data). Walks outside ``tests/`` -- an engine or
script function walking the root it is handed -- are out of this walk too; the
ones the read audit found are :data:`ENGINE_SITES`, declared.
"""
from __future__ import annotations

import ast
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Iterator, NamedTuple

REPO = Path(__file__).resolve().parent.parent

MARKER = "live-tree: ok"
#: The marker is a COMMENT with a reason; prose naming it marks nothing.
MARKER_COMMENT = re.compile(r"#\s*" + re.escape(MARKER))
MARKER_WITH_REASON = re.compile(r"#\s*" + re.escape(MARKER) + r"\s+--\s+\S")

_ROOT_NAME = re.compile(r"_?(?:REPO_ROOT|REPO|ROOT)")
COMPUTED = "<computed>"

#: The files this walker never reads: the helper whose fallback IS the walk,
#: and this census.
SELF = frozenset({"tests/_live_tree.py", "tests/_live_tree_census.py"})

_METHOD_KINDS = frozenset({"rglob", "glob", "iterdir", "walk"})
_FUNC_KINDS = {
    ("os", "walk"): "os.walk", ("os", "scandir"): "os.scandir", ("os", "listdir"): "os.listdir",
    ("glob", "glob"): "glob.glob", ("glob", "iglob"): "glob.iglob", ("shutil", "copytree"): "copytree",
}
_BARE_KINDS = {"copytree": "copytree", "safe_rglob": "safe_rglob", "_safe_rglob": "safe_rglob",
               "walk": "os.walk", "scandir": "os.scandir", "listdir": "os.listdir", "iglob": "glob.iglob"}
_ROUTERS = frozenset({"keep_in_checkout"})
_WALK_CALL_ATTRS = frozenset({"walk", "rglob", "glob", "iterdir", "scandir", "listdir"})


class Site(NamedTuple):
    rel: str        # tests/<file>.py
    line: int
    owner: str      # the enclosing qualname, or <module>
    kind: str
    root: str       # the repo-relative directory walked ('' = the root)
    routed: bool
    marked: bool

    @property
    def key(self) -> str:
        """The ratchet's unit: the owner, what it calls, and what it walks --
        so routing one walk in an owner and adding another there is a new
        key, never a swap under one allowance."""
        return f"{self.rel}::{self.owner}::{self.kind}::{self.root or '<root>'}"


# ── The scanner walkers, derived ─────────────────────────────────────────────

@lru_cache(maxsize=None)
def scanner_walkers() -> frozenset[str]:
    """The top-level functions of ``espalier/scanners/*.py`` that walk the tree
    they are handed: a function whose body calls ``os.walk``, a ``*rglob``
    helper, or a path's ``rglob`` / ``glob`` / ``iterdir`` / ``scandir`` /
    ``listdir`` -- or calls a function of its own module that does (to a fixed
    point). Derived, so a new scanner's ``scan_repo`` is a site the day it
    lands."""
    names: set[str] = set()
    for path in sorted((REPO / "espalier" / "scanners").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        funcs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        walks = {name for name, f in funcs.items() if any(_is_walk_call(c) for c in ast.walk(f))}
        changed = True
        while changed:
            changed = False
            for name, f in funcs.items():
                if name in walks:
                    continue
                called = {c.func.id for c in ast.walk(f) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
                if called & walks:
                    walks.add(name)
                    changed = True
        names |= {n for n in walks if not n.startswith("__")}
    return frozenset(names)


def _is_walk_call(node: ast.AST) -> bool:
    """A directory listing: ``os.walk`` / ``os.scandir`` / ``os.listdir``, a
    ``*rglob`` helper, or a path's ``rglob`` / ``glob`` / ``iterdir``.
    ``ast.walk`` is a tree walk, not a directory one."""
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Attribute):
        receiver = f.value.id if isinstance(f.value, ast.Name) else None
        if receiver == "os":
            return f.attr in ("walk", "scandir", "listdir")
        if receiver in ("ast", "re", "fnmatch"):
            return False
        return f.attr in _WALK_CALL_ATTRS - {"walk", "scandir", "listdir"} or f.attr.endswith("rglob")
    return isinstance(f, ast.Name) and f.id.endswith("rglob")


# ── Root resolution ──────────────────────────────────────────────────────────

class _ElementOf(ast.expr):
    """A loop target's binding when the loop runs over a NAME (``for root in
    roots``): resolved as the first rooted element of the container that name
    (or attribute) is bound to."""

    _fields = ("container",)

    def __init__(self, container: ast.expr):
        super().__init__()
        self.container = container


class _InScope(ast.expr):
    """A parameter's binding from a call site: ``value`` is resolved in the
    scope of the call that passed it (its function, its class), not the
    callee's."""

    _fields = ("value",)

    def __init__(self, value: ast.expr, at: ast.AST):
        super().__init__()
        self.value = value
        self.at = at


class _Scope:
    """Name bindings visible at a site: innermost function first, then its
    class, then the module; plus the parameters this module binds by call."""

    def __init__(self, layers: list[dict[str, list[ast.expr]]]):
        self.layers = layers

    def lookup(self, name: str) -> list[ast.expr]:
        for layer in self.layers:
            if name in layer:
                return layer[name]
        return []


def _bindings(nodes) -> dict[str, list[ast.expr]]:
    """name -> the expressions it is bound to among ``nodes`` (assignment,
    annotated assignment, walrus; a ``for`` / comprehension target over a
    literal tuple or list binds each element; a ``with ... as`` binds its
    expression)."""
    out: dict[str, list[ast.expr]] = {}

    def add(target, value):
        if isinstance(target, ast.Name) and value is not None:
            out.setdefault(target.id, []).append(value)

    for node in nodes:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                add(t, node.value)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
            add(node.target, node.value)
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            it = node.iter
            if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id in ("sorted", "list", "tuple") and it.args:
                it = it.args[0]
            if isinstance(it, (ast.Tuple, ast.List, ast.Set)):
                for elt in it.elts:
                    add(node.target, elt)
            elif isinstance(it, (ast.Name, ast.Attribute)):
                add(node.target, _ElementOf(it))
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            add(node.optional_vars, node.context_expr)
    return out


def _own_nodes(scope_node) -> Iterator[ast.AST]:
    """The nodes of a function or class body, not descending into nested
    function or class definitions (their bindings are their own)."""
    stack = list(ast.iter_child_nodes(scope_node))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _file_climb(expr: ast.expr) -> int | None:
    """How far above the module's own directory a ``Path(__file__)`` chain
    climbs: ``Path(__file__).parent`` is 0 (``tests/``), ``.parent.parent`` and
    ``.parents[1]`` are 1 (the root). None when ``expr`` is not such a chain."""
    ups = 0
    node = expr
    while True:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("resolve", "absolute") and not node.args:
            node = node.func.value
        elif isinstance(node, ast.Attribute) and node.attr == "parent":
            ups += 1
            node = node.value
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents" \
                and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int):
            ups += node.slice.value + 1
            node = node.value.value
        else:
            break
    if isinstance(node, ast.Call) and ast.unparse(node.func) in ("Path", "pathlib.Path") and len(node.args) == 1 \
            and isinstance(node.args[0], ast.Name) and node.args[0].id == "__file__" and ups >= 1:
        return ups - 1
    return None


def _strip(base: str, levels: int) -> str | None:
    """``base`` climbed ``levels`` directories; None once it leaves the
    checkout. A computed part stays computed."""
    parts = base.split("/") if base else []
    if parts and parts[-1] == COMPUTED:
        return base
    if levels > len(parts):
        return None
    return "/".join(parts[:len(parts) - levels])


def _join(base: str, part: str) -> str:
    return f"{base}/{part}".strip("/") if base else part.strip("/")


class _Resolver:
    def __init__(self, scope: _Scope, imported: dict[str, str], classes: dict[str, dict[str, list[ast.expr]]],
                 here_class: str | None, at=None, funcs=None, methods=None, repo_modules=frozenset()):
        self.scope = scope
        self.imported = imported
        self.classes = classes
        self.here_class = here_class
        #: builds the resolver for another node's scope (a call site); None
        #: where only one scope exists (an imported module's top level)
        self.at = at
        #: this module's functions and each class's methods, by name: a call of
        #: one is rooted when what it returns is
        self.funcs = funcs or {}
        self.methods = methods or {}
        #: names bound to a module of this repository (``import espalier.x``,
        #: ``from tests import y``): ``Path(<it>.__file__)`` is a computed root
        self.repo_modules = repo_modules

    def _returned_root(self, defs, depth: int) -> str | None:
        for d in defs:
            for node in _own_nodes(d):
                if isinstance(node, ast.Return) and node.value is not None:
                    other = self.at(node) if self.at is not None else self
                    r = other.root(node.value, depth + 1)
                    if r is not None:
                        return r
        return None

    def root(self, expr, depth: int = 0) -> str | None:
        """The repo-relative directory ``expr`` names, or None when it is not
        rooted in the checkout."""
        if expr is None or depth > 8:
            return None
        if isinstance(expr, _InScope):
            other = self.at(expr.at) if self.at is not None else self
            return other.root(expr.value, depth + 1)
        if isinstance(expr, _ElementOf):
            return self._element_root(expr.container, depth + 1)
        if isinstance(expr, ast.Name):
            for value in self.scope.lookup(expr.id):
                r = self.root(value, depth + 1)
                if r is not None:
                    return r
            if expr.id in self.imported:
                return self.imported[expr.id]
            if _ROOT_NAME.fullmatch(expr.id):
                return ""
            return None
        if isinstance(expr, ast.IfExp):
            roots = {r for r in (self.root(expr.body, depth + 1), self.root(expr.orelse, depth + 1)) if r is not None}
            if len(roots) == 1:
                return roots.pop()
            return _join("", COMPUTED) if roots else None
        if isinstance(expr, ast.Attribute) and expr.attr == "parent" and _file_climb(expr) is None:
            base = self.root(expr.value, depth + 1)
            return None if base is None else _strip(base, 1)
        if isinstance(expr, ast.Subscript) and isinstance(expr.value, ast.Attribute) and expr.value.attr == "parents" \
                and isinstance(expr.slice, ast.Constant) and isinstance(expr.slice.value, int) and _file_climb(expr) is None:
            base = self.root(expr.value.value, depth + 1)
            return None if base is None else _strip(base, expr.slice.value + 1)
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Call) \
                and isinstance(expr.value.func, ast.Name) and expr.value.func.id == "type" \
                and len(expr.value.args) == 1 and isinstance(expr.value.args[0], ast.Name) \
                and expr.value.args[0].id in ("self", "cls"):
            for value in self.classes.get(self.here_class or "", {}).get(expr.attr, []):
                r = self.root(value, depth + 1)
                if r is not None:
                    return r
            return None
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
            owner = expr.value.id
            cls = self.here_class if owner in ("self", "cls") else owner
            for value in self.classes.get(cls or "", {}).get(expr.attr, []):
                r = self.root(value, depth + 1)
                if r is not None:
                    return r
            return None
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
            base = self.root(expr.left, depth + 1)
            if base is None:
                return None
            if isinstance(expr.right, ast.Constant) and isinstance(expr.right.value, str):
                return _join(base, expr.right.value)
            return _join(base, COMPUTED)
        if isinstance(expr, ast.JoinedStr):
            for v in expr.values:
                if isinstance(v, ast.FormattedValue):
                    r = self.root(v.value, depth + 1)
                    if r is not None:
                        return _join(r, COMPUTED)
            return None
        if isinstance(expr, ast.Call):
            f = expr.func
            if isinstance(f, ast.Attribute) and f.attr in ("resolve", "absolute") and not expr.args:
                return self.root(f.value, depth + 1)
            if isinstance(f, ast.Attribute) and f.attr == "joinpath":
                base = self.root(f.value, depth + 1)
                if base is None:
                    return None
                if expr.args and all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in expr.args):
                    return _join(base, "/".join(a.value for a in expr.args))
                return _join(base, COMPUTED)
            if ast.unparse(f) in ("Path", "pathlib.Path") and len(expr.args) == 1 \
                    and isinstance(expr.args[0], ast.Attribute) and expr.args[0].attr == "__file__" \
                    and isinstance(expr.args[0].value, ast.Name) and expr.args[0].value.id in self.repo_modules:
                return _join("", COMPUTED)
            if (ast.unparse(f) in ("str", "Path", "pathlib.Path")) and len(expr.args) == 1:
                climb = _file_climb(expr)
                if climb is not None:
                    return None
                return self.root(expr.args[0], depth + 1)
            if ast.unparse(f) in ("Path", "pathlib.Path") and len(expr.args) > 1:
                base = self.root(expr.args[0], depth + 1)
                if base is None:
                    return None
                rest = expr.args[1:]
                if all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in rest):
                    return _join(base, "/".join(a.value for a in rest))
                return _join(base, COMPUTED)
            if isinstance(f, ast.Name) and f.id in self.funcs:
                return self._returned_root(self.funcs[f.id], depth)
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                cls = self.here_class if f.value.id in ("self", "cls") else f.value.id
                if f.attr in self.methods.get(cls or "", {}):
                    return self._returned_root(self.methods[cls][f.attr], depth)
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "os" and f.attr == "fspath" \
                    and expr.args:
                return self.root(expr.args[0], depth + 1)
            if ast.unparse(f) == "os.path.join" and expr.args:
                base = self.root(expr.args[0], depth + 1)
                if base is None:
                    return None
                rest = expr.args[1:]
                if all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in rest):
                    return _join(base, "/".join(a.value for a in rest)) if rest else base
                return _join(base, COMPUTED)
        climb = _file_climb(expr)
        if climb is not None:
            return "" if climb >= 1 else "tests"
        return None

    def _element_root(self, container, depth: int) -> str | None:
        """The first rooted element of the tuple / list / set ``container``
        is bound to (through names, ``self.X`` / ``cls.X``, ``sorted()`` /
        ``list()`` / ``tuple()``)."""
        if container is None or depth > 8:
            return None
        if isinstance(container, (ast.Tuple, ast.List, ast.Set)):
            roots = {r for r in (self.root(elt, depth + 1) for elt in container.elts) if r is not None}
            if not roots:
                return None
            if len(roots) == 1:
                return roots.pop()
            # several roots: the loop walks each, so the site is a computed root
            # under their common directory
            common = [p for p in zip(*(r.split("/") for r in roots)) if len(set(p)) == 1]
            return _join("/".join(p[0] for p in common), COMPUTED)
        if isinstance(container, ast.Call) and isinstance(container.func, ast.Name) \
                and container.func.id in ("sorted", "list", "tuple") and container.args:
            return self._element_root(container.args[0], depth + 1)
        if isinstance(container, _InScope):
            other = self.at(container.at) if self.at is not None else self
            return other._element_root(container.value, depth + 1)
        values: list[ast.expr] = []
        if isinstance(container, ast.Name):
            values = self.scope.lookup(container.id)
        elif isinstance(container, ast.Attribute) and isinstance(container.value, ast.Name):
            owner = container.value.id
            cls = self.here_class if owner in ("self", "cls") else owner
            values = self.classes.get(cls or "", {}).get(container.attr, [])
        for value in values:
            r = self._element_root(value, depth + 1)
            if r is not None:
                return r
        return None


# ── The walk ─────────────────────────────────────────────────────────────────

def census_files() -> list[Path]:
    """Every module directly under ``tests/`` this walker reads."""
    return [p for p in sorted((REPO / "tests").glob("*.py"))
            if p.relative_to(REPO).as_posix() not in SELF]


@lru_cache(maxsize=None)
def _module_roots(stem: str) -> dict[str, str]:
    """The module-level rooted names of ``tests/<stem>.py`` (for imports)."""
    path = REPO / "tests" / f"{stem}.py"
    if not path.is_file():
        return {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    module = _bindings(_own_nodes(tree))
    resolver = _Resolver(_Scope([module]), {}, {}, None)
    out = {}
    for name, values in module.items():
        for v in values:
            r = resolver.root(v)
            if r is not None:
                out[name] = r
                break
    return out


def _marked(lines: list[str], line: int) -> bool:
    """A marker on the call's own first line, or in the comment-only block
    directly above it."""
    if MARKER_COMMENT.search(lines[line - 1]):
        return True
    i = line - 2
    while i >= 0 and lines[i].strip().startswith("#"):
        if MARKER_COMMENT.search(lines[i]):
            return True
        i -= 1
    return False


#: The base a listing called without one lists: ``checkout_files()``'s
#: default, the checkout root (``Path(__file__).parent.parent`` from tests/).
_CHECKOUT_ROOT_EXPR = ast.parse("Path(__file__).parent.parent", mode="eval").body


def sites_in(text: str, rel: str, *, listings: tuple[str, ...] = ()) -> list[Site]:
    """Every live-tree enumeration in one module's source.

    ``listings`` names calls that list git's view of the checkout (the
    ``tests/_live_tree.py`` listings, ``require_tracked_paths``): a call of one
    rooted in the checkout is then a site too, of its own name's kind and
    routed by construction. The ratchet passes none -- a listing is the routed
    spelling, not work -- and ``tests/test_marker_taxonomy.py``'s tree-wide
    sweep census passes them, to ask where a test enumerates the tree at all.
    The base is the first argument, ``base=`` or ``repo_root=``; a listing
    called with none (``checkout_files()``) lists the checkout root."""
    tree = ast.parse(text)
    lines = text.splitlines()
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    imported: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("tests."):
            roots = _module_roots(node.module.split(".", 1)[1])
            for a in node.names:
                if a.name in roots:
                    imported[a.asname or a.name] = roots[a.name]
    module_layer = _bindings(_own_nodes(tree))
    classes = {c.name: _bindings(_own_nodes(c)) for c in ast.walk(tree) if isinstance(c, ast.ClassDef)}
    # parameters this module binds: a call ``f(rooted, ...)`` / ``f(p=rooted)`` / a default
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    by_name: dict[str, list[ast.FunctionDef]] = {}
    for f in functions:
        by_name.setdefault(f.name, []).append(f)
    param_bind: dict[int, dict[str, list[ast.expr]]] = {id(f): {} for f in functions}
    for f in functions:
        args = f.args.posonlyargs + f.args.args
        defaults = f.args.defaults
        for a, d in zip(args[len(args) - len(defaults):], defaults):
            param_bind[id(f)].setdefault(a.arg, []).append(d)
        for a, d in zip(f.args.kwonlyargs, f.args.kw_defaults):
            if d is not None:
                param_bind[id(f)].setdefault(a.arg, []).append(d)
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        fname = call.func.id if isinstance(call.func, ast.Name) else (
            call.func.attr if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
            and call.func.value.id in ("self", "cls") else None)
        for f in by_name.get(fname or "", []):
            args = f.args.posonlyargs + f.args.args
            offset = 1 if args and args[0].arg in ("self", "cls") and isinstance(call.func, ast.Attribute) else 0
            for i, value in enumerate(call.args):
                if i + offset < len(args):
                    param_bind[id(f)].setdefault(args[i + offset].arg, []).append(_InScope(value, call))
            for kw in call.keywords:
                if kw.arg:
                    param_bind[id(f)].setdefault(kw.arg, []).append(_InScope(kw.value, call))

    def enclosing(node) -> list[ast.AST]:
        chain = []
        cur = parents.get(node)
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                chain.append(cur)
            cur = parents.get(cur)
        return chain

    funcs = {n.name: [n] for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    methods = {c.name: {m.name: [m] for m in c.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
               for c in ast.walk(tree) if isinstance(c, ast.ClassDef)}
    repo_modules = frozenset(
        (a.asname or a.name.split(".")[0]) for n in ast.walk(tree) if isinstance(n, ast.Import)
        for a in n.names if a.name.split(".")[0] in ("espalier", "tests")
    ) | frozenset(
        (a.asname or a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
        and n.module.split(".")[0] in ("espalier", "tests") for a in n.names
    )
    layer_cache: dict[int, dict[str, list[ast.expr]]] = {}

    def layer_of(scope_node) -> dict[str, list[ast.expr]]:
        if id(scope_node) not in layer_cache:
            layer = _bindings(_own_nodes(scope_node))
            for k, v in param_bind.get(id(scope_node), {}).items():
                layer.setdefault(k, []).extend(v)
            layer_cache[id(scope_node)] = layer
        return layer_cache[id(scope_node)]

    def resolver_at(node) -> _Resolver:
        chain = enclosing(node)
        layers = [layer_of(s) for s in chain if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))]
        layers.append(module_layer)
        here_class = next((c.name for c in chain if isinstance(c, ast.ClassDef)), None)
        return _Resolver(_Scope(layers), imported, classes, here_class, resolver_at, funcs, methods, repo_modules)

    # which scanner module a scanner call runs: ``from espalier.scanners import
    # freshness as scn`` binds ``scn``; ``from espalier.scanners.freshness
    # import discover_fragments`` binds the function's own name
    scanner_module: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "espalier.scanners":
            scanner_module.update({a.asname or a.name: a.name for a in n.names})
        elif isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("espalier.scanners."):
            scanner_module.update({a.asname or a.name: n.module.rsplit(".", 1)[1] for a in n.names})
        elif isinstance(n, ast.Import):
            scanner_module.update({a.asname: a.name.rsplit(".", 1)[1] for a in n.names
                                   if a.asname and a.name.startswith("espalier.scanners.")})

    # ``from shutil import copytree as ct`` / ``from os import walk as w``: a
    # bare call under an alias is the function it names
    # (a bare ``walk`` / ``listdir`` / ``copytree`` counts only when the module
    # imported it from there; a ``*rglob`` helper counts by its name)
    aliases = {a.asname or a.name: a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
               and n.module in ("os", "shutil", "glob") for a in n.names}
    walkers = scanner_walkers()
    out: list[Site] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id in aliases:
            f = ast.Name(id=aliases[f.id], ctx=ast.Load())
        kind = target = None
        if isinstance(f, ast.Attribute) and f.attr in _METHOD_KINDS and not (
                isinstance(f.value, ast.Name) and f.value.id in ("os", "glob", "shutil")):
            kind, target = f.attr, f.value
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and (f.value.id, f.attr) in _FUNC_KINDS:
            kind = _FUNC_KINDS[(f.value.id, f.attr)]
            # ``glob.glob(pattern, root_dir=ROOT)`` lists under root_dir
            target = next((k.value for k in node.keywords if k.arg == "root_dir"), None) or (
                node.args[0] if node.args else next(
                    (k.value for k in node.keywords if k.arg in ("top", "path", "pathname", "src")), None))
        elif isinstance(f, ast.Name) and f.id in _BARE_KINDS and (
                f.id.endswith("rglob") or node.func is not f):
            kind = _BARE_KINDS[f.id]
            target = node.args[0] if node.args else next(
                (k.value for k in node.keywords if k.arg in ("top", "path", "pathname", "src", "root")), None)
        elif isinstance(f, ast.Name) and f.id in listings:
            kind = f.id
            target = node.args[0] if node.args else next(
                (k.value for k in node.keywords if k.arg in ("base", "repo_root")), _CHECKOUT_ROOT_EXPR)
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.attr in ("safe_rglob", "_safe_rglob"):
            kind, target = "safe_rglob", (node.args[0] if node.args else None)
        else:
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
            if name in walkers:
                kind, target = f"scanner:{name}", (node.args[0] if node.args else next(
                    (k.value for k in node.keywords if k.arg in ("root", "repo_root")), None))
        if kind is None or target is None:
            continue
        chain = enclosing(node)
        root = resolver_at(node).root(target)
        if root is None:
            continue
        parent = parents.get(node)
        routed = kind in listings or isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name) \
            and parent.func.id in _ROUTERS and parent.args and parent.args[0] is node
        if routed and kind.startswith("scanner:"):
            module = scanner_module.get(f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                                        else (f.id if isinstance(f, ast.Name) else ""), "")
            routed = module not in RAISING_SCANNERS
        owner = ".".join(c.name for c in reversed(chain)) or "<module>"
        out.append(Site(rel, node.lineno, owner, kind, root, routed, _marked(lines, node.lineno)))
    return sorted(out, key=lambda s: (s.rel, s.line))


#: Scanners whose walk RAISES on what it reads before any result comes back,
#: so ``keep_in_checkout`` around one filters nothing: the freshness scanner's
#: ``discover_fragments`` raises ``FreshnessError`` on a duplicate fragment id,
#: and a gitignored Windows copy-duplicate ``docs/CONVENTIONS (1).md`` carries
#: one. A call of one is never routed by the filter; it reads a
#: ``copy_checkout`` copy, or its walk is narrowed to git's view.
RAISING_SCANNERS = frozenset({"freshness"})


@lru_cache(maxsize=None)
def live_tree_sites() -> tuple[Site, ...]:
    """Every site in ``tests/``, read once per process (the ratchet's tests
    and the probe-parity test all read it)."""
    out: list[Site] = []
    for path in census_files():
        out += sites_in(path.read_text(encoding="utf-8"), path.relative_to(REPO).as_posix())
    return tuple(out)


#: Live-tree walks on another seat's lane that had not merged when the ratchet
#: was dated: neither the probe nor the ratchet counts them while they are
#: present, and their absence is not a stale entry, so the ratchet passes
#: whichever lane merges second. Keyed by file and function name (the owner's
#: last qualname part), since the walk's spelling on that lane is not readable
#: here. The remainder lane routes each onto git's view and deletes its entry.
OPEN_LANE_OWNERS: dict[tuple[str, str], str] = {
    ("tests/test_mail.py", "_naming_prose_offenders"):
        "air-work's lane/board-seats-and-asks, unmerged 2026-10-15 (air-work 86bd22, air 538ae3): "
        "an rglob('*.md') under docs/, .claude/ and memory/ through exclude_worktrees",
}


def on_an_open_lane(site: Site) -> bool:
    return (site.rel, site.owner.split(".")[-1]) in OPEN_LANE_OWNERS


def unrouted_sites() -> list[Site]:
    return [s for s in live_tree_sites() if not s.routed and not s.marked and not on_an_open_lane(s)]


def unrouted_count() -> int:
    return len(unrouted_sites())


#: Live-tree walks OUTSIDE tests/ that this census cannot read -- an engine or
#: script function walking the root it is handed -- found by the 2026-10-15
#: read audit (the whole suite under an audit hook recording each test's reads
#: and listings outside git's view). Each is a member of DEF-2013 for its
#: second lane, declared rather than derived because the census reads tests/
#: only: the row stays open while any is listed, and the lane that routes one
#: deletes its entry with the evidence. Lane three (assign 7850b3, 2026-10-15)
#: closed all five: the build copy leaves out a nested checkout by its own .git
#: (espalier/artifact_parity.py::_build_tree_ignore); the release gate's docs and
#: the fence checker's basename candidates are git's view
#: (scripts/release_check.py::_public_doc_paths,
#: scripts/check_pack_fences.py::_checkout_view); and the two reflect walks are
#: the adopter's, so the live-tree tests that run them read their result through
#: keep_in_checkout (test_reflection's live-repo scan, test_reflect_protocol's
#: live-tree parity), as do the two that run scripts/check_exception_policy.py's
#: walk (a sixth, found by that lane's failure-mode review). A walk found later
#: is declared here again, with an open row whose probe runs this file: the
#: ratchet reds a declared site no live probe reads.
ENGINE_SITES: dict[str, str] = {}


def probe_open() -> bool:
    """The census's verdict: open while any enumeration in tests/ is neither
    routed nor marked, or any engine site is listed. A
    boolean, not a count: two lanes that each route a site would both rewrite
    a pinned count to the same lower number, the merge would take both edits
    as one, and the record would be wrong on main (one shared record two
    lanes recompute, Core Rule 15)."""
    return unrouted_count() > 0 or bool(ENGINE_SITES)


def probe_line() -> str:
    """What ``python3 tests/_live_tree_census.py`` prints on its last line."""
    return str(probe_open())


if __name__ == "__main__":
    # --list: the work list (every unrouted site, then the engine sites); bare:
    # the census's verdict on its last line
    if "--list" in sys.argv[1:]:
        for s in unrouted_sites():
            print(f"{s.rel}:{s.line} {s.owner} {s.kind} {s.root or '<root>'}")
        for where, why in ENGINE_SITES.items():
            print(f"{where} (engine) {why}")
        print(f"{unrouted_count()} unrouted in tests/, {len(ENGINE_SITES)} engine sites")
    print(probe_line())
