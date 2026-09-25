"""TP-147 147-F: every hook source file except ``_maintenance_mode.py``
itself must reference the env-var name via ``_maintenance_mode.ENV_VAR``,
NOT as a hardcoded string literal.

The contract walks each ``tools/cc/hooks/*.py`` AST and inspects every
``ast.Constant`` whose value is a string. Hits — i.e. ``"… ESPALIER_MAINTENANCE_MODE …"``
embedded in a runtime string literal — are flagged.

Docstrings (the first ``Expr(Constant(str))`` at module / class /
function scope) are exempted because they describe behavior, not
runtime decisions. ``#``-comments are exempted by construction
(comments aren't AST nodes). The remaining nodes are *runtime* string
literals — the surface that silently desyncs when the canonical
constant is renamed. F-strings compile to ``ast.JoinedStr`` whose
sub-Constants don't include the env-var name (the name lives in the
``FormattedValue`` expression as a ``Name`` / ``Attribute`` node);
substituting f-strings everywhere is the standard fix.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
EXEMPT_FILES = frozenset({"_maintenance_mode.py"})
ENV_VAR_LITERAL = "ESPALIER_MAINTENANCE_MODE"


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Return id() of the Constant nodes that are docstrings.

    A docstring is the very first statement of Module / FunctionDef /
    AsyncFunctionDef / ClassDef when that statement is
    ``Expr(Constant(str))``. We collect those Constants by ``id()``
    so the main walk can skip them without re-implementing scope
    tracking.
    """
    docstring_ids: set[int] = set()
    scope_nodes = (
        ast.Module,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
    )
    for node in ast.walk(tree):
        if not isinstance(node, scope_nodes):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstring_ids.add(id(first.value))
    return docstring_ids


def test_no_maintenance_mode_literal_in_hook_string_constants():
    drift: list[tuple[str, int, str]] = []
    for py in sorted(HOOK_DIR.glob("*.py")):
        if py.name in EXEMPT_FILES:
            continue
        text = py.read_text(encoding="utf-8")
        tree = ast.parse(text)
        docstring_ids = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            if not isinstance(node.value, str):
                continue
            if id(node) in docstring_ids:
                continue
            if ENV_VAR_LITERAL in node.value:
                drift.append((py.name, node.lineno, node.value[:80]))
    assert not drift, (
        f"TP-147 147-F: hook source files contain runtime string "
        f"literals carrying {ENV_VAR_LITERAL!r} — these silently "
        f"desync from the canonical _maintenance_mode.ENV_VAR. "
        f"Replace with f-string referencing _maintenance_mode.ENV_VAR.\n"
        f"Drift sites:\n  " + "\n  ".join(
            f"{name}:{line}: {snippet!r}" for name, line, snippet in drift
        )
    )
