"""The test modules that run on a contributor's tree and skip in every CI
checkout, derived from their skip reasons.

Not a test module (leading underscore) -- no marker classification needed.

``tests/README.md``'s *Which tests are selected at all* exists to expose that
the local suite and the CI suite skip different sets: a test gated on a path
that is present on a contributor's working tree but gitignored is absent from
every CI checkout, so it runs locally and skips in CI. The README's rule for
such a test is to say so in its skip reason, because that string is the only
place the distinction is visible. This module reads exactly that string, so the
README's list of those modules is generated
(``scripts/generate_doc_regions.py``'s ``local-only-skips`` region) instead of
hand-kept: the hand list named four modules while nine were gated that way
on 2026-10-30, two of them with a reason that did not say so (DEF-486).

A module is in the population when any skip in it --
``pytest.skip(...)``, ``pytest.mark.skip(...)``, ``pytest.mark.skipif(...)`` or
``pytest.importorskip(...)`` -- carries a reason that, read statically, says
the gate is gitignored or local-only (:data:`LOCAL_ONLY_REASON_RE`). A reason is
read statically: a string literal, an implicit or ``+`` concatenation of
literals, an f-string's literal parts, or a module-level name bound to one of
those. A reason built at run time from anything else is not read, and a test
gated on a gitignored path whose reason does not say so is not in the
population: it breaks the README's rule, and a reader of a skip summary cannot
see it either.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from tests._live_tree import REPO_ROOT, checkout_glob

#: What a skip reason says when the path it is gated on is gitignored on a
#: contributor's tree: ``gitignored`` (or ``git-ignored``, ``ignored by git``)
#: or ``local-only`` (or ``local only``).
LOCAL_ONLY_REASON_RE = re.compile(r"git-?ignored|ignored by git|local[- ]only", re.IGNORECASE)

#: The skip calls read, by dotted name, and the positional index of the reason
#: in each (``None``: keyword only -- ``skipif``'s positional arguments are
#: conditions, and ``importorskip``'s are the module and its version).
_SKIP_CALLS: dict[str, int | None] = {
    "pytest.skip": 0,
    "pytest.mark.skip": 0,
    "pytest.mark.skipif": None,
    "pytest.importorskip": None,
}


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _literal(node: ast.AST, names: dict[str, ast.AST], depth: int = 0) -> str | None:
    """The text of ``node`` where it is fixed in the source, else ``None``. An
    f-string's interpolations read as ``{}``: the words around them carry the
    claim."""
    if depth > 8:
        return None
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) and isinstance(part.value, str) else "{}"
            for part in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left, names, depth + 1), _literal(node.right, names, depth + 1)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.Name) and node.id in names:
        return _literal(names[node.id], names, depth + 1)
    return None


def _module_names(tree: ast.Module) -> dict[str, ast.AST]:
    """Module-level ``NAME = <value>`` bindings, the last one winning."""
    names: dict[str, ast.AST] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            names[stmt.targets[0].id] = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            names[stmt.target.id] = stmt.value
    return names


def skip_reasons(source: str) -> list[str]:
    """Every skip reason in ``source`` that reads statically, in source order."""
    tree = ast.parse(source)
    names = _module_names(tree)
    reasons: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted(node.func)
        if dotted not in _SKIP_CALLS:
            continue
        candidates = [kw.value for kw in node.keywords if kw.arg in ("reason", "msg")]
        position = _SKIP_CALLS[dotted]
        if position is not None and len(node.args) > position:
            candidates.append(node.args[position])
        for candidate in candidates:
            text = _literal(candidate, names)
            if text is not None:
                reasons.append(text)
    return reasons


def local_only_skip_modules(repo_root: Path = REPO_ROOT) -> dict[str, list[str]]:
    """``{"tests/test_x.py": [reason, ...]}`` for every test module in git's
    view of ``repo_root`` whose skips say the gate is gitignored or local-only,
    each module's matching reasons distinct and in source order. A module that
    does not parse is left out: the suite's collection reds on it first."""
    repo_root = Path(repo_root)
    found: dict[str, list[str]] = {}
    for path in checkout_glob(repo_root / "tests", "test_*.py", root=repo_root):
        try:
            reasons = skip_reasons(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        matching = list(dict.fromkeys(r for r in reasons if LOCAL_ONLY_REASON_RE.search(r)))
        if matching:
            found[path.relative_to(repo_root).as_posix()] = matching
    return found
