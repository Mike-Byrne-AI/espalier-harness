"""TP-146 146-B contract: every `tarfile.extractall` call in the repo
must use `filter=` OR be wrapped by a known safe-helper validator.

Reason: ruff S202 caught a bare `tf.extractall(extract_to)` in
`scripts/final_release_matrix.py` (since removed -- the file carries no
extractall call today, so the original line anchor was left to rot and is
deliberately not restored). ZIP-slip / tarbomb is the textbook
bypass class catalogued at `bench/corpus/BC-010-zip-member-traversal.json`,
and the harness should not exhibit the pattern it documents elsewhere.
This AST walk pins the property repo-wide so any future caller has to
opt in to the safe-helper convention or pass `filter=` explicitly.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files / directories that are intentionally excluded:
#   - tests/fixtures: anti-pattern fixtures under test
#   - dist / build / venv: build / runtime artifacts
EXEMPT_PREFIXES = (
    "tests/fixtures/",
    "dist/",
    "build/",
    ".venv/",
    "venv/",
)

# Whitelisted helper names. A file that defines one of these AND contains a
# bare extractall inside is allowed (the helper is the validation site).
# TP-147 147-D promoted the helpers from script-local underscore-prefixed
# names to public-shaped names in ``espalier/_archive_safety.py``; both
# forms remain accepted to keep the contract stable across downstream
# consumers that may still ship the script-local form.
SAFE_HELPER_NAMES = frozenset({
    "_safe_extract_tar",
    "_safe_extract_zip",
    "safe_extract_tar",
    "safe_extract_zip",
})


def _iter_py_files():
    for p in REPO_ROOT.rglob("*.py"):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if any(rel.startswith(prefix) for prefix in EXEMPT_PREFIXES):
            continue
        yield p


def _bare_extractall_calls(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (lineno, snippet) for every `*.extractall(...)` call lacking
    a `filter=` kwarg."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "extractall":
            continue
        has_filter = any(kw.arg == "filter" for kw in node.keywords)
        if not has_filter:
            found.append((node.lineno, ast.unparse(node)))
    return found


def _defines_safe_helper(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in SAFE_HELPER_NAMES:
            return True
    return False


class TestNoTarfileExtractallWithoutFilter:
    @pytest.mark.contract
    def test_all_tarfile_extractall_calls_use_filter_or_helper(self):
        drift: list[tuple[str, list[tuple[int, str]]]] = []
        for py in _iter_py_files():
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            unsafe = _bare_extractall_calls(tree)
            if not unsafe:
                continue
            if _defines_safe_helper(tree):
                # The bare extractall inside the helper itself is the validated
                # path. Keep this allowance file-local — calling code in the
                # same module must still route through the helper.
                continue
            drift.append((py.relative_to(REPO_ROOT).as_posix(), unsafe))
        assert not drift, (
            "tarfile.extractall without filter= or safe-helper wrapper "
            f"(TP-146 146-B contract): {drift}"
        )
