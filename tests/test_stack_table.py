"""The stack table: one place that says what each stack is.

``tools/cc/_stack_table.py`` holds, per stack, the source suffixes and their
language, the manifests and lockfiles, the Node package managers with their
argv templates, the dependency and output directories, a fallback lint, the
rules rendered only for that stack, and whether the scanners can read its
source. The hooks import it; the engine imports a byte copy,
``espalier/_stack_table.py`` (mirror row ``stack-table``), written by
``scripts/sync_vendor_cc.py``.

What this module pins: the engine copy is a byte mirror of the source, the
sync script writes the row the registry declares, and both copies answer the
same. A drift is caught here because the engine and the hooks would otherwise
read two different tables, each looking authoritative to its own side.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

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
