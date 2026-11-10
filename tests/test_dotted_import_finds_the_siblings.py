"""A ``tools/cc`` module that bare-imports a sibling at its top imports by its
dotted name too.

Such a module is loaded two ways: bare, with its own directory already on
``sys.path`` (a script run from that directory, or the hook that loaded it,
put it there), and as ``tools.cc.hooks.<module>`` or ``tools.cc.<module>``
from the repo root, where nothing has. A module that trusts every importer to
have put its directory on the path imports inside the full suite only when a
file collected ahead of it already did, and standalone it fails with
ModuleNotFoundError. ``_bash_patterns`` shipped that order dependence and
took the guarded own-directory insert for it (``if _HERE not in sys.path``);
six more modules carried it until they took the same insert.

The population is derived, never typed: every ``*.py`` in the two directories
whose module-level code (inside a ``try``, ``if`` or class block too, never
inside a function body) imports a sibling of its own directory by the bare
name where a failed import would raise. An import under ``if TYPE_CHECKING:``
or ``if __name__ == "__main__":`` never runs on import, and one inside a ``try`` whose handler catches the failure and
does not raise again is a deliberate fallback that loads either way; a row for
a module whose only sibling imports are those could never go red, so it is
left out. Each member is imported by its dotted name in a fresh interpreter
of its own, run isolated (``-I``: no PYTHONPATH, no user site, no script
directory) with the repo root alone added. The child first checks that no
``sys.path`` entry is the module's own directory, so a pass is never borrowed
from a path some other importer left. Each module gets its own process because one insert in a
shared process would hide every later module's missing one.
"""
# slow-exempt: one short import child per module in the population (37 on 2026-11-09), measured then: 3.2 s for the module serial on the Air at load 3.1, the largest child 0.19 s
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from tests._live_tree import checkout_glob
from tests._wait_budget import scaled

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_CC = REPO_ROOT / "tools" / "cc"
HOOKS_DIR = TOOLS_CC / "hooks"

# The directories whose modules are loaded both ways.
DIRECTORIES = (HOOKS_DIR, TOOLS_CC)

# One import child's bound. write_guard's import graph, the largest here,
# loads in well under a second on the Air.
IMPORT_SECONDS = 30

# The child: refuse a borrowed path, then import by the dotted name.
CHILD = """\
import importlib, os, sys
root, dotted, own = sys.argv[1], sys.argv[2], sys.argv[3]
def same(entry):
    return os.path.normcase(os.path.realpath(entry or os.curdir)) == os.path.normcase(os.path.realpath(own))
borrowed = [entry for entry in sys.path if same(entry)]
if borrowed:
    print("borrowed: the module's directory was on sys.path before the import: %r" % borrowed)
    sys.exit(3)
sys.path.insert(0, root)
importlib.import_module(dotted)
print("ok")
"""


# The exception names whose handler catches a failed import.
IMPORT_FAILURES = frozenset({"ImportError", "ModuleNotFoundError", "Exception", "BaseException"})


def _catches_a_failed_import(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    caught = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(isinstance(name, ast.Name) and name.id in IMPORT_FAILURES for name in caught)


def _raises_again(handler: ast.ExceptHandler) -> bool:
    """The handler itself raises: a ``raise`` in a function or class it
    defines (a fallback's body) runs later, if ever, so it does not count."""
    stack: list[ast.AST] = list(handler.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return False


def _falls_back(node: ast.Try | ast.TryStar) -> bool:
    """A failed import in this ``try`` body is caught and never raised again."""
    return any(_catches_a_failed_import(handler) and not _raises_again(handler)
               for handler in node.handlers)


def _never_runs_on_import(node: ast.If) -> bool:
    """``if TYPE_CHECKING:`` or ``if __name__ == "__main__":``."""
    test = node.test
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
        return True
    return (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
            and test.left.id == "__name__" and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__")


def _raising_module_level_imports(tree: ast.Module):
    """Every import an import of the module runs where a failure would raise:
    the body, walked into ``try``, ``if``, ``with`` and class blocks (a class
    body runs at import), never into a function, an ``if TYPE_CHECKING:`` or
    ``if __name__ == "__main__":`` body, or the body of a ``try`` that falls
    back."""
    stack: list[ast.AST] = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.If) and _never_runs_on_import(node):
            stack.extend(node.orelse)
            continue
        if isinstance(node, (ast.Try, ast.TryStar)) and _falls_back(node):
            stack.extend([*node.handlers, *node.orelse, *node.finalbody])
            continue
        stack.extend(ast.iter_child_nodes(node))


def bare_sibling_imports(path: Path, siblings: frozenset[str]) -> list[str]:
    """The siblings ``path`` imports by the bare name at its module level,
    where a failed import would raise."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    named: list[str] = []
    for node in _raising_module_level_imports(tree):
        if isinstance(node, ast.Import):
            named += [alias.name for alias in node.names if alias.name.split(".")[0] in siblings]
        elif (isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
              and node.module.split(".")[0] in siblings):
            named.append(node.module)
    return named


def population() -> list[tuple[str, Path]]:
    """(dotted name, own directory) for each module in the class."""
    rows: list[tuple[str, Path]] = []
    for directory in DIRECTORIES:
        modules = sorted(path for path in checkout_glob(directory, "*.py") if path.stem != "__init__")
        stems = frozenset(path.stem for path in modules)
        package = ".".join(directory.relative_to(REPO_ROOT).parts)
        for path in modules:
            if bare_sibling_imports(path, stems - {path.stem}):
                rows.append((f"{package}.{path.stem}", directory))
    return rows


POPULATION = population()


class TestThePopulation:
    def test_the_population_holds_both_directories_known_members(self):
        """A derivation that drops a directory or stops reading imports would
        pass every row below by having none; these members each import a
        sibling bare at their top."""
        dotted = {name for name, _ in POPULATION}
        for member in ("tools.cc.hooks._bash_patterns", "tools.cc.hooks._speedbump",
                       "tools.cc.hooks.write_guard", "tools.cc.statusline", "tools.cc.mail"):
            assert member in dotted, (member, sorted(dotted))

    def test_only_an_import_whose_failure_would_raise_counts(self, tmp_path):
        """Kept: a re-raising ``try``, an ``if`` and a class body. Left out: a
        function body, a ``try`` that falls back, ``if TYPE_CHECKING:``, a
        ``__main__`` block."""
        source = tmp_path / "probe.py"
        source.write_text(
            "import os\n"
            "from typing import TYPE_CHECKING\n"
            "try:\n    import _alpha\nexcept ImportError:\n    raise\n"
            "if os.name:\n    from _beta import thing\n"
            "def later():\n    import _gamma\n"
            "class Late:\n    import _delta\n"
            "try:\n    from _epsilon import run\nexcept ImportError:\n"
            "    def run():\n        raise RuntimeError('fallback')\n"
            "if TYPE_CHECKING:\n    import _zeta\n"
            "if __name__ == '__main__':\n    import _eta\n",
            encoding="utf-8",
        )
        siblings = frozenset({"_alpha", "_beta", "_gamma", "_delta", "_epsilon", "_zeta", "_eta"})
        assert sorted(bare_sibling_imports(source, siblings)) == ["_alpha", "_beta", "_delta"]


class TestEachModuleImportsByItsDottedName:
    @pytest.mark.parametrize(("dotted", "own"), POPULATION, ids=[name for name, _ in POPULATION])
    def test_imports_in_a_fresh_isolated_process(self, dotted, own, tmp_path):
        proc = subprocess.run(
            [sys.executable, "-I", "-c", CHILD, str(REPO_ROOT), dotted, str(own)],
            cwd=str(tmp_path), capture_output=True, text=True, encoding="utf-8",
            timeout=scaled(IMPORT_SECONDS),
        )
        assert proc.returncode != 3, proc.stdout
        assert proc.returncode == 0, f"{dotted} did not import by its dotted name:\n{proc.stderr}"
        assert proc.stdout.strip() == "ok", proc.stdout
