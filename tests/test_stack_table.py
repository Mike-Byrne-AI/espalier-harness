"""The stack table: one place that says what each stack is.

``tools/cc/_stack_table.py`` holds, per stack, the source suffixes and their
language, the manifests and lockfiles, the Node package managers with their
argv templates, the dependency and output directories, a fallback lint, the
rules rendered only for that stack, and whether the scanners can read its
source. The hooks import it; the engine imports a byte copy,
``espalier/_stack_table.py`` (mirror row ``stack-table``), written by
``scripts/sync_vendor_cc.py``.

What this module holds:

* the engine copy is a byte mirror of the source, and the sync script writes
  the row the registry declares;
* the hand-list ratchet: every collection literal in the shipped production
  roots that spells stack vocabulary is a projection of the table, carries a
  ``stack-table: ok purpose-scoped -- <reason>`` marker, or is a dated
  baseline site still waiting for its lane. The baseline only shrinks;
* the floor pin: each seed name stays a member of the table projection it
  belongs to. Once the hand lists are projections no literal spells a name the
  table lost, so the ratchet alone cannot see the loss -- this pin does.

The ratchet walks ``espalier/`` (minus the two mirrors under
``espalier/_vendor/`` and the engine copy) and ``tools/cc/`` (minus the
table). ``scripts/`` is outside the walk on purpose: it is self-host tooling
that never ships, and its two dependency lists
(``check_pack_fences._RESOLVE_SKIP``, ``symbol_census._SKIP_DIR_PARTS``) walk
this repository only.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "tools" / "cc" / "_stack_table.py"
ENGINE_COPY = REPO / "espalier" / "_stack_table.py"


def _load_hook_table():
    """The tools/cc/ copy, loaded by path (never a plain import: that would
    put espalier on a tools/cc/ module's import graph)."""
    name = "_stack_table_under_test"
    spec = importlib.util.spec_from_file_location(name, SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_sync_script():
    spec = importlib.util.spec_from_file_location(
        "_sync_vendor_cc_for_stack_table", REPO / "scripts" / "sync_vendor_cc.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── The engine copy ──────────────────────────────────────────────────────────


class TestTheEngineCopyIsAByteMirror:
    """The ``stack-table`` row of espalier/mirror_registry.py."""

    def test_the_engine_copy_is_byte_identical_to_the_source(self):
        assert SOURCE.is_file(), "tools/cc/_stack_table.py is missing"
        assert ENGINE_COPY.is_file(), (
            "espalier/_stack_table.py is missing -- run `python3 scripts/sync_vendor_cc.py`"
        )
        assert ENGINE_COPY.read_bytes() == SOURCE.read_bytes(), (
            "espalier/_stack_table.py drifted from tools/cc/_stack_table.py -- edit the "
            "tools/cc/ source, then run `python3 scripts/sync_vendor_cc.py`"
        )

    def test_the_sync_script_writes_the_registry_row(self):
        """The script cannot import the registry (it is stdlib-only), so the
        two spellings of the pair are held equal here."""
        from espalier import mirror_registry

        row = mirror_registry.row("stack-table")
        script = _load_sync_script()
        source_name = row.sot.removeprefix("tools/cc/")
        assert script.ENGINE_COPIES == {source_name: row.mirrors[0]}
        assert row.sync is not None and row.sync.endswith("scripts/sync_vendor_cc.py")

    def test_the_sync_check_reports_a_drifted_engine_copy(self, monkeypatch, tmp_path):
        """``--check`` is the read-only twin: a copy that differs is drift."""
        script = _load_sync_script()
        root = tmp_path / "checkout"
        (root / "tools" / "cc").mkdir(parents=True)
        (root / "espalier").mkdir()
        (root / "tools" / "cc" / "_stack_table.py").write_bytes(b"A = 1\n")
        (root / "espalier" / "_stack_table.py").write_bytes(b"A = 2\n")
        monkeypatch.setattr(script, "SRC", root / "tools" / "cc")
        monkeypatch.setattr(script, "ENGINE_ROOT", root)
        assert script.engine_drift() == ["espalier/_stack_table.py"]
        (root / "espalier" / "_stack_table.py").write_bytes(b"A = 1\n")
        assert script.engine_drift() == []

    def test_a_scratch_source_never_writes_a_real_engine(self, monkeypatch, tmp_path):
        """A SRC outside ENGINE_ROOT's checkout (a test's scratch tree) maps to
        no engine copy at all, so sync() cannot reach the real espalier/."""
        script = _load_sync_script()
        scratch = tmp_path / "src"
        scratch.mkdir()
        (scratch / "_stack_table.py").write_bytes(b"A = 1\n")
        monkeypatch.setattr(script, "SRC", scratch)
        assert script._engine_pairs() == []

    def test_the_table_imports_only_the_standard_library(self):
        """Both sides import it, so it may import neither side."""
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        assert imported <= {"__future__", "typing"}, imported

    def test_both_copies_answer_the_same(self):
        from espalier import _stack_table as engine

        hook = _load_hook_table()
        assert hook.suffix_to_language() == engine.suffix_to_language()
        assert hook.manifest_names() == engine.manifest_names()
        assert hook.lockfile_owners() == engine.lockfile_owners()
        assert hook.dependency_dirs() == engine.dependency_dirs()
        assert hook.script_runners() == engine.script_runners()


# ── The hand-list ratchet ────────────────────────────────────────────────────

MARKER = "stack-table: ok purpose-scoped"
#: The marker is a COMMENT: prose that names it (a docstring, an obligation
#: string) marks nothing.
_MARKER_COMMENT = re.compile(r"#\s*" + re.escape(MARKER))
_MARKER_WITH_REASON = re.compile(r"#\s*" + re.escape(MARKER) + r"\s+--\s+\S")
_ROOTS = ("espalier", "tools/cc")
_TABLE_FILES = frozenset({"espalier/_stack_table.py", "tools/cc/_stack_table.py"})
_CTORS = frozenset({"frozenset", "set", "tuple", "list"})

#: The fixed seed, written here and not read from the table: a name deleted
#: from the table must still be looked for. Dependency directories (by name,
#: at any depth; ``.venv`` is vocabulary a hand list may spell, though Python
#: environments are not table members), the Node and Python source suffixes,
#: the manifests the census counts, and the lockfiles.
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

#: Sites still spelling stack vocabulary by hand, waiting for the lanes that
#: derive or mark them. Dated 2026-10-06 (the package-manager lane); 25 sites.
#: It may only SHRINK: a lane that derives a site deletes its entry here, and an
#: entry whose site no longer spells the vocabulary reds until it is deleted.
#: Empty when the dependency-directory lane lands. The count is per owner, so a
#: second hand list added beside a baseline one still reds.
_PENDING_SITES: dict[str, int] = {
    # source suffixes and manifests (the source-and-manifests lane)
    "espalier/analyze.py::SUFFIX_TO_LANGUAGE": 1,
    "tools/cc/hooks/_hook_utils.py::SOURCE_LANGUAGE_EXTENSIONS": 1,
    "espalier/analyze.py::MANIFEST_NAMES": 1,
    "espalier/analyze.py::_has_python_signals": 1,
    "espalier/analyze.py::detect_tests": 1,
    "tools/cc/hooks/_hook_utils.py::PROJECT_MANIFEST_NAMES": 1,
    "tools/cc/hooks/plan_guard.py::PLAN_REQUIRED_ROOT_FILES": 1,
    # dependency directories (the dependency-directory lane)
    "espalier/_safe_walk.py::DEPENDENCY_TREE_DIRS": 1,
    "espalier/analyze.py::DEFAULT_SKIP_PARTS": 1,
    "espalier/analyze.py::KNOWN_GENERATED": 1,
    "espalier/diffing.py::EPHEMERAL_ZONES": 1,
    "espalier/fuse.py::_NONGIT_SKIP_DIRS": 1,
    "espalier/reflect_protocol.py::_WALK_SKIP_DIRS": 1,
    "espalier/release_noise.py::TRANSIENT_DIRS": 1,
    "espalier/repo_mode.py::_WALK_SKIP_DIRS": 1,
    "espalier/scanners/encoding_contracts.py::PRUNE_DIRS": 1,
    "espalier/scanners/exceptions.py::DEFAULT_EXCLUDE": 1,
    "espalier/scanners/godfiles.py::DEFAULT_EXCLUDE": 1,
    "espalier/scanners/perf_smells.py::DEFAULT_EXCLUDE": 1,
    "espalier/scanners/prints.py::DEFAULT_EXCLUDE": 1,
    "espalier/scanners/test_loosening.py::DEFAULT_EXCLUDE": 1,
    "espalier/strengthen.py::_EXEMPT_PREFIXES": 1,
    "tools/cc/hooks/_bash_patterns.py::SAFE_EPHEMERAL_DIRS": 1,
    "tools/cc/reflect_protocol.py::_WALK_SKIP_DIRS": 1,
    "tools/cc/sister_site_probe.py::_ADOPTER_PRUNE_NAMES": 1,
}


def _vocabulary():
    """The table's names joined with the seed: what a hand list may not spell."""
    from espalier import _stack_table as table

    return (
        SEED_DEPENDENCY_DIRS | table.dependency_dirs(),
        SEED_SOURCE_SUFFIXES | table.source_extensions(),
        SEED_MANIFESTS | frozenset(table.manifest_names()),
        SEED_LOCKFILES | frozenset(table.lockfile_owners()),
    )


def _production_files():
    for root in _ROOTS:
        for path in sorted((REPO / root).rglob("*.py")):
            rel = path.relative_to(REPO).as_posix()
            if rel.startswith("espalier/_vendor/") or rel in _TABLE_FILES:
                continue
            if "__pycache__" in path.parts:
                continue
            yield rel, path


def _owners(tree: ast.AST) -> dict[int, str]:
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


def _display_strings(node: ast.AST) -> list[str] | None:
    """The string elements of a collection literal, or ``None`` when ``node``
    is not one. Shapes read: a set, list or tuple display; a dict display's
    keys; ``frozenset(...)`` / ``set(...)`` / ``tuple(...)`` / ``list(...)``
    over one; ``"a b".split()``; and a ``+`` of any of these."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _display_strings(node.left), _display_strings(node.right)
        if left is None or right is None:
            return None
        return left + right
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in _CTORS and len(node.args) == 1:
            return _display_strings(node.args[0])
        if (
            isinstance(func, ast.Attribute) and func.attr == "split"
            and isinstance(func.value, ast.Constant) and isinstance(func.value.value, str)
        ):
            sep = None
            if node.args and isinstance(node.args[0], ast.Constant):
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


def _spells_vocabulary(strings: list[str], vocab) -> bool:
    deps, suffixes, manifests, lockfiles = vocab
    names = {s.rstrip("/") for s in strings}
    return bool(
        names & deps
        or len(names & suffixes) >= 2
        or len(names & manifests) >= 2
        or names & lockfiles
    )


def _literal_sites(vocab):
    """``(rel, owner, lineno, marked)`` per collection literal that spells the
    vocabulary. A literal nested in a reported one (a tuple inside a ``+``,
    the set inside ``frozenset(...)``) is the same site, reported once."""
    sites = []
    for rel, path in _production_files():
        text = path.read_text(encoding="utf-8-sig")
        lines = text.splitlines()
        tree = ast.parse(text)
        owners = _owners(tree)
        covered: set[int] = set()
        for node in ast.walk(tree):
            if id(node) in covered:
                continue
            strings = _display_strings(node)
            if strings is None or not _spells_vocabulary(strings, vocab):
                continue
            for inner in ast.walk(node):
                covered.add(id(inner))
            lineno = node.lineno
            marked = any(
                _MARKER_COMMENT.search(lines[i])
                for i in (lineno - 1, lineno - 2) if 0 <= i < len(lines)
            )
            sites.append((rel, owners.get(id(node)) or "<module>", lineno, marked))
    return sites


class TestEveryHandListIsDerivedOrMarked:
    """The ratchet. A hand list of stack vocabulary in the shipped roots is
    either a projection of the table (and then no literal spells it), marked
    purpose-scoped with a reason, or a baseline site still pending."""

    def test_the_walk_reads_the_shipped_roots(self):
        files = {rel for rel, _ in _production_files()}
        assert "espalier/analyze.py" in files and "tools/cc/hooks/_hook_utils.py" in files
        assert not any(rel.startswith("espalier/_vendor/") for rel in files)
        assert not files & _TABLE_FILES

    def test_no_new_hand_list_spells_stack_vocabulary(self):
        found = Counter(
            f"{rel}::{owner}" for rel, owner, _line, marked in _literal_sites(_vocabulary())
            if not marked
        )
        new = {k: n for k, n in found.items() if n > _PENDING_SITES.get(k, 0)}
        assert not new, (
            "a collection literal spells stack vocabulary by hand: "
            f"{sorted(new)}. Derive it from tools/cc/_stack_table.py (the engine reads "
            "espalier/_stack_table.py), or mark it `# stack-table: ok purpose-scoped -- "
            "<why its purpose is not the stack's>` on its line or the line above."
        )

    def test_the_baseline_only_shrinks(self):
        """An entry whose site was derived or marked is deleted here, so the
        baseline is the live list of pending sites and never a stale allowance."""
        found = Counter(
            f"{rel}::{owner}" for rel, owner, _line, marked in _literal_sites(_vocabulary())
            if not marked
        )
        stale = {k: n for k, n in _PENDING_SITES.items() if found.get(k, 0) < n}
        assert not stale, (
            f"baseline entries no longer spelled by hand: {sorted(stale)} -- delete "
            "them from _PENDING_SITES (the baseline only shrinks)"
        )

    def test_every_marker_sits_on_a_list_that_spells_the_vocabulary(self):
        """A marker on a list that no longer spells the vocabulary (a projection,
        or a list emptied of it) is stale: it would exempt the next hand list
        written in its place."""
        marked_lines = {
            (rel, line) for rel, _owner, line, marked in _literal_sites(_vocabulary()) if marked
        }
        stale = []
        for rel, path in _production_files():
            for number, text in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
                if not _MARKER_COMMENT.search(text):
                    continue
                if not _MARKER_WITH_REASON.search(text):
                    stale.append(f"{rel}:{number} (no `-- <reason>`)")
                elif not ({(rel, number), (rel, number + 1)} & marked_lines):
                    stale.append(f"{rel}:{number}")
        assert not stale, f"stack-table markers with no hand list beside them: {stale}"


class TestTheRatchetReadsEveryLiteralShape:
    """The ratchet is only as wide as the shapes it reads."""

    @pytest.mark.parametrize("source", [
        '_X = {"node_modules", "dist"}',
        '_X = frozenset(["dist", ".pnpm-store"])',
        '_X = ("a",) + ("node_modules",)',
        '_X = "dist node_modules".split()',
        '_X = {"pyproject.toml": 1, "go.mod": 2}',
        '_X = (".py", ".mjs")',
        '_X = ["bun.lockb"]',
    ])
    def test_a_hand_list_in_any_shape_is_found(self, source):
        tree = ast.parse(source)
        hits = [
            node for node in ast.walk(tree)
            if (s := _display_strings(node)) is not None and _spells_vocabulary(s, _vocabulary())
        ]
        assert hits, source

    @pytest.mark.parametrize("source", [
        '_X = {"dist", "build"}',
        '_X = (".py",)',
        '_X = ("source", "target")',
        '_X = ["package.json"]',
    ])
    def test_a_list_without_the_vocabulary_is_not(self, source):
        tree = ast.parse(source)
        hits = [
            node for node in ast.walk(tree)
            if (s := _display_strings(node)) is not None and _spells_vocabulary(s, _vocabulary())
        ]
        assert not hits, source


class TestTheTableKeepsItsSeedNames:
    """The floor pin. Once a hand list derives from the table no literal spells
    its names, so a name deleted from the table is invisible to the ratchet;
    each seed name is held to the projection it belongs to instead."""

    def test_every_dependency_directory_stays_in_the_table(self):
        from espalier import _stack_table as table

        missing = (SEED_DEPENDENCY_DIRS - {".venv"}) - table.dependency_dirs()
        assert not missing, missing

    def test_python_environments_stay_out_of_the_dependency_directories(self):
        """A virtual environment is the adopter's own tooling, not a prune by
        name at any depth (the rule DEPENDENCY_TREE_DIRS documents)."""
        from espalier import _stack_table as table

        assert not {".venv", "venv", "vendor"} & table.dependency_dirs()

    def test_every_output_directory_stays_in_the_table(self):
        from espalier import _stack_table as table

        assert SEED_OUTPUT_DIRS <= table.output_dirs()

    def test_every_node_and_python_suffix_stays_in_the_table(self):
        from espalier import _stack_table as table

        assert SEED_SOURCE_SUFFIXES <= table.source_extensions()

    def test_every_manifest_stays_in_the_table(self):
        from espalier import _stack_table as table

        missing = (SEED_MANIFESTS - {"composer.json"}) - frozenset(table.manifest_names())
        assert not missing, missing

    def test_every_lockfile_names_its_package_manager(self):
        from espalier import _stack_table as table

        owners = table.lockfile_owners()
        assert {name: owners.get(name) for name in SEED_LOCKFILES} == {
            "package-lock.json": "npm",
            "pnpm-lock.yaml": "pnpm",
            "yarn.lock": "yarn",
            "bun.lock": "bun",
            "bun.lockb": "bun",
        }
