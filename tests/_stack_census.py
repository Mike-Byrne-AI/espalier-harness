"""The census of hand lists that spell stack vocabulary: one walker, two readers.

``tests/test_stack_table.py`` holds the ratchet on it, and the forward ledger's
probe for the stack-registry row runs this file (``python3
tests/_stack_census.py`` from the repository root prints the number of
unmarked sites). One walker for both, so the ratchet and the probe cannot
disagree about what a site is: a probe that read fewer shapes than the ratchet
could strike the row while the ratchet still held a site, or keep it open
after the ratchet reached zero.

A SITE is a collection literal in ``espalier/`` (minus the two mirrors under
``espalier/_vendor/`` and the engine's copy of the table) or ``tools/cc/``
(minus the table) whose strings name a dependency or build-output directory,
two or more source suffixes, two or more manifests, or a lockfile. The shapes
read: a set, list or tuple display; a dict display's keys; ``frozenset(...)``,
``set(...)``, ``tuple(...)`` or ``list(...)`` over one; ``"a b".split()``; and
a ``+`` of any of these. A literal nested in a reported one is the same site.

Not read, and known: a list built by ``.append`` / ``.add`` / ``.update``
calls, a regular-expression alternation (``"node_modules|dist"``), and a list
holding ONE source suffix or ONE manifest beside other names (the thresholds
are two, the census's rule for "a list of them"). And a build-output name
alone: ``target`` is an English word, and with it as a trigger the walk found
four more literals on 2026-10-06, three of them a dict key or an MCP field
name (``"target"``) and one a real build-output list
(``analyze.detect_generated_zones``'s ``{"dist", "build", "target"}``). The
real one is named in the stack registry pack for the dependency-directory
lane; the floor pin still holds ``target`` in the table.

A site is MARKED when a ``# stack-table: ok purpose-scoped -- <reason>``
comment sits on the literal's own first line, or in the block of comment-only
lines directly above it. A trailing marker on one line never reaches the next
literal.

``scripts/`` is outside the walk: it is self-host tooling that never ships,
and its two dependency lists walk this repository only. Stdlib only, plus the
engine's copy of the table for the vocabulary.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parent.parent

MARKER = "stack-table: ok purpose-scoped"
#: The marker is a COMMENT: prose that names it (a docstring, an obligation
#: string) marks nothing.
MARKER_COMMENT = re.compile(r"#\s*" + re.escape(MARKER))
MARKER_WITH_REASON = re.compile(r"#\s*" + re.escape(MARKER) + r"\s+--\s+\S")

ROOTS = ("espalier", "tools/cc")
TABLE_FILES = frozenset({"espalier/_stack_table.py", "tools/cc/_stack_table.py"})
_CTORS = frozenset({"frozenset", "set", "tuple", "list"})

#: The fixed seed, written here and not read from the table: a name deleted
#: from the table must still be looked for. Dependency directories (by name,
#: at any depth; ``.venv`` is vocabulary a hand list may spell, though Python
#: environments are not table members), build output, the Node and Python
#: source suffixes, the manifests the census counts, and the lockfiles.
SEED_DEPENDENCY_DIRS = frozenset({
    "node_modules", "bower_components", "jspm_packages", ".yarn", ".pnpm-store", ".venv",
})
SEED_OUTPUT_DIRS = frozenset({"target"})
SEED_SOURCE_SUFFIXES = frozenset({
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts",
    ".astro", ".vue", ".svelte",
})
SEED_MANIFESTS = frozenset({
    "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
    "setup.py", "setup.cfg", "requirements.txt", "Pipfile", "Gemfile", "composer.json",
})
SEED_LOCKFILES = frozenset({
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb",
})


#: The test roots the plan guard exempts beside a manifest (TP-472 2-A);
#: compared without the trailing slash, like every other name here.
SEED_TEST_DIRS = frozenset({"tests/", "test/", "__tests__/", "spec/"})


class Vocabulary(NamedTuple):
    directories: frozenset[str]
    suffixes: frozenset[str]
    manifests: frozenset[str]
    lockfiles: frozenset[str]
    test_dirs: frozenset[str]


class Site(NamedTuple):
    rel: str        # repo-relative path
    owner: str      # the enclosing def/class, or the module-level target
    lineno: int     # the literal's first line
    marked: bool
    covers: tuple[int, ...]  # the lines a marker may sit on for this site


def vocabulary() -> Vocabulary:
    """The table's names joined with the seed: what a hand list may not spell."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from espalier import _stack_table as table

    return Vocabulary(
        # Build-output names (``target``) are not a trigger: see the module docstring.
        SEED_DEPENDENCY_DIRS | table.dependency_dirs(),
        SEED_SOURCE_SUFFIXES | table.source_extensions(),
        SEED_MANIFESTS | frozenset(table.manifest_names()),
        SEED_LOCKFILES | frozenset(table.lockfile_owners()),
        frozenset(
            d.rstrip("/") for d in SEED_TEST_DIRS | {d for row in table.STACKS for d in row.test_dirs}
        ),
    )


def production_files(root: Path = REPO):
    for top in ROOTS:
        for path in sorted((root / top).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel.startswith("espalier/_vendor/") or rel in TABLE_FILES:
                continue
            if "__pycache__" in path.parts:
                continue
            yield rel, path


def owners(tree: ast.AST) -> dict[int, str]:
    """``id(node) -> owner``: the enclosing def/class qualname, or the target of
    the module-level assignment the node sits in (the census's labelling)."""
    names: dict[int, str] = {}

    def visit(node: ast.AST, label: str) -> None:
        for child in ast.iter_child_nodes(node):
            lab = label
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                lab = child.name if not label else f"{label}.{child.name}"
            elif isinstance(child, (ast.Assign, ast.AnnAssign)) and not label:
                target = child.targets[0] if isinstance(child, ast.Assign) else child.target
                lab = ast.unparse(target)
            names[id(child)] = lab
            visit(child, lab)

    visit(tree, "")
    return names


def display_strings(node: ast.AST) -> list[str] | None:
    """The string elements of a collection literal, or ``None`` when ``node``
    is not one (the shapes are listed in the module docstring)."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = display_strings(node.left), display_strings(node.right)
        if left is None or right is None:
            return None
        return left + right
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in _CTORS and len(node.args) == 1:
            return display_strings(node.args[0])
        if (
            isinstance(func, ast.Attribute) and func.attr == "split"
            and isinstance(func.value, ast.Constant) and isinstance(func.value.value, str)
        ):
            sep = None
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                sep = node.args[0].value
            return func.value.value.split(sep)
        return None
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        elts = node.elts
    elif isinstance(node, ast.Dict):
        elts = [k for k in node.keys if k is not None]
    else:
        return None
    return [e.value for e in elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def spells_vocabulary(strings: list[str], vocab: Vocabulary) -> bool:
    names = {s.rstrip("/") for s in strings}
    return bool(
        names & vocab.directories
        or len(names & vocab.suffixes) >= 2
        or len(names & vocab.manifests) >= 2
        or names & vocab.lockfiles
        or len(names & vocab.test_dirs) >= 2
    )


def marker_lines(lines: list[str], lineno: int) -> tuple[int, ...]:
    """The 1-based lines a marker for a literal starting on ``lineno`` may sit
    on: that line, and the comment-only lines directly above it."""
    covered = [lineno]
    i = lineno - 2
    while i >= 0 and lines[i].lstrip().startswith("#"):
        covered.append(i + 1)
        i -= 1
    return tuple(covered)


def literal_sites(vocab: Vocabulary | None = None, root: Path = REPO) -> list[Site]:
    """Every collection literal in the walked roots that spells the vocabulary."""
    vocab = vocab or vocabulary()
    sites = []
    for rel, path in production_files(root):
        text = path.read_text(encoding="utf-8-sig")
        lines = text.splitlines()
        tree = ast.parse(text)
        names = owners(tree)
        covered: set[int] = set()
        for node in ast.walk(tree):
            if id(node) in covered:
                continue
            strings = display_strings(node)
            if strings is None or not spells_vocabulary(strings, vocab):
                continue
            for inner in ast.walk(node):
                covered.add(id(inner))
            lineno = node.lineno  # type: ignore[attr-defined]
            span = marker_lines(lines, lineno)
            marked = any(MARKER_COMMENT.search(lines[n - 1]) for n in span if 0 < n <= len(lines))
            sites.append(Site(rel, names.get(id(node)) or "<module>", lineno, marked, span))
    return sites


def unmarked_count(root: Path = REPO) -> int:
    return sum(1 for site in literal_sites(root=root) if not site.marked)


if __name__ == "__main__":
    print(unmarked_count())
