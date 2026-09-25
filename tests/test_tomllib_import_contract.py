"""tomllib-import contract — no *unguarded* ``import tomllib`` on a
version-supported surface.

``tomllib`` is a stdlib module only on Python 3.11+, but the project declares
``requires-python = ">=3.10"`` and the CI matrix tests 3.10. An unguarded
``import tomllib`` therefore raises ``ModuleNotFoundError`` on 3.10 — at
*collection* if it is a module-level import in a collected test (aborting the
whole 3.10 leg), or at *call time* if it sits inside a function a test reaches.
Both shipped in one session:

- a module-level bare import in ``tests/test_benchmark_release_hygiene.py``
  aborted 3.10 collection; and
- an in-function bare import in ``scripts/wheel_smoke.py`` (reached by
  ``tests/test_wheel_smoke.py``) failed only once collection got that far.

So this contract flags an ``import tomllib`` at ANY nesting depth unless it is
guarded by one of the two sanctioned forms:

- a ``sys.version_info`` ``if`` that falls back to ``tomli`` (the sibling idiom), or
- a ``try/except`` (the ``espalier/_compat.py`` shim, ``final_release_matrix.py``).

``from espalier._compat import tomllib`` is fine — it is not an ``import tomllib``.

This is the mechanical lock that catches the class on ANY interpreter,
including the maintainer's, so a 3.10-only break never again depends on the CI
matrix to surface it. (Version-agnostic fix + contract-lock is the standard
response when a bug cannot be reproduced on the host interpreter.)

Scope: ``tests/`` (pytest-collected) + ``espalier/`` (shipped to adopters) +
``scripts/`` (release/CI helpers, several of which tests import and call — the
under-scoping that let ``wheel_smoke.py`` through the first time).
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_SCANNED_ROOTS = ("tests", "espalier", "scripts")


def _is_version_guard(test: ast.expr) -> bool:
    """True when an ``if`` test references ``sys.version_info`` — the sanctioned
    3.10/3.11 fork guarding a ``tomllib`` import."""
    return any(
        isinstance(n, ast.Attribute) and n.attr == "version_info"
        for n in ast.walk(test)
    )


def _unguarded_tomllib_import_lines(tree: ast.AST) -> list[int]:
    """Line numbers of every ``import tomllib`` NOT protected by a
    ``sys.version_info`` guard or a ``try/except`` — at any nesting depth."""
    offenders: list[int] = []

    def walk(node: ast.AST, guarded: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if (
                isinstance(child, ast.Import)
                and any(alias.name == "tomllib" for alias in child.names)
                and not guarded
            ):
                offenders.append(child.lineno)
            child_guarded = guarded
            if isinstance(child, ast.Try):
                child_guarded = True
            elif isinstance(child, ast.If) and _is_version_guard(child.test):
                child_guarded = True
            walk(child, child_guarded)

    walk(tree, False)
    return offenders


def _unguarded_tomllib_imports() -> list[str]:
    """Return ``"path:line"`` for every unguarded ``import tomllib`` across the
    scanned roots."""
    offenders: list[str] = []
    for root in _SCANNED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):  # pragma: no cover -- unreadable/partial file
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            offenders.extend(f"{rel}:{ln}" for ln in _unguarded_tomllib_import_lines(tree))
    return offenders


class TestNoBareTomllibImport:
    def test_no_unguarded_tomllib_import(self) -> None:
        offenders = _unguarded_tomllib_imports()
        assert not offenders, (
            "Unguarded `import tomllib` breaks Python 3.10 (stdlib only on "
            "3.11+; project requires-python >=3.10) — at collection if "
            "module-level in a test, or at call time if a test reaches it. "
            "Guard it:\n"
            "    if sys.version_info >= (3, 11):\n"
            "        import tomllib\n"
            "    else:  # pragma: no cover -- 3.10 fallback\n"
            "        import tomli as tomllib  # type: ignore[no-redef]\n"
            "or a try/except, or `from espalier._compat import tomllib`, or (for "
            "a stdlib-only script) parse the value without a TOML library. "
            "Offenders:\n  " + "\n  ".join(offenders)
        )
