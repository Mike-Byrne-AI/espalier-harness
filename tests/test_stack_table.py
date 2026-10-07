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
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from _stack_census import (
    MARKER_COMMENT,
    MARKER_WITH_REASON,
    SEED_DEPENDENCY_DIRS,
    SEED_LOCKFILES,
    SEED_MANIFESTS,
    SEED_OUTPUT_DIRS,
    SEED_SOURCE_SUFFIXES,
    TABLE_FILES,
    Site,
    literal_sites,
    production_files,
    unmarked_count,
    vocabulary,
)

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

    def test_the_sync_writes_the_engine_copy(self, monkeypatch, tmp_path):
        """The write half: one sync run, pointed at a scratch checkout, lands
        the source in both mirrors. Without it a refactor that dropped the
        engine loop stays green until the next table edit."""
        script = _load_sync_script()
        root = tmp_path / "checkout"
        (root / "tools" / "cc").mkdir(parents=True)
        (root / "espalier" / "_vendor" / "cc").mkdir(parents=True)
        (root / "tools" / "cc" / "_stack_table.py").write_bytes(b"A = 1\n")
        monkeypatch.setattr(script, "SRC", root / "tools" / "cc")
        monkeypatch.setattr(script, "VENDOR", root / "espalier" / "_vendor" / "cc")
        monkeypatch.setattr(script, "ENGINE_ROOT", root)
        assert script.sync() == (2, 0)
        assert (root / "espalier" / "_stack_table.py").read_bytes() == b"A = 1\n"
        assert (root / "espalier" / "_vendor" / "cc" / "_stack_table.py").read_bytes() == b"A = 1\n"
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

#: Sites still spelling stack vocabulary by hand, waiting for the lanes that
#: derive or mark them. Dated 2026-10-06 (the package-manager lane); 25 sites.
#: A lane that derives or marks a site deletes its entry here AND lowers
#: ``_PENDING_CEILING``; an entry whose site no longer spells the vocabulary
#: reds until it is deleted. The count is per owner, so a second hand list
#: added beside a baseline one reds -- but deriving one list while adding
#: another under the SAME owner nets to zero here, which is why the ceiling and
#: the ledger probe (the same walker, counting literals, not owners) exist.
#: Empty when the dependency-directory lane lands.
_PENDING_SITES: dict[str, int] = {
    # dependency directories (the dependency-directory lane)
    "espalier/analyze.py::KNOWN_GENERATED": 1,
    "espalier/diffing.py::EPHEMERAL_ZONES": 1,
    "espalier/fuse.py::_NONGIT_SKIP_DIRS": 1,
    "espalier/release_noise.py::TRANSIENT_DIRS": 1,
    "espalier/scanners/encoding_contracts.py::PRUNE_DIRS": 1,
    "espalier/scanners/exceptions.py::DEFAULT_EXCLUDE": 1,
    "espalier/scanners/godfiles.py::DEFAULT_EXCLUDE": 1,
    "espalier/scanners/perf_smells.py::DEFAULT_EXCLUDE": 1,
    "espalier/scanners/prints.py::DEFAULT_EXCLUDE": 1,
    "espalier/scanners/test_loosening.py::DEFAULT_EXCLUDE": 1,
    "espalier/strengthen.py::_EXEMPT_PREFIXES": 1,
    "tools/cc/hooks/_bash_patterns.py::SAFE_EPHEMERAL_DIRS": 1,
}

#: The baseline's ceiling: it only falls. Each lane lowers it by what it
#: derived, dated. 2026-10-06: 25 (the package-manager lane; nothing derived yet).
#: 2026-10-07: 20 (the source-and-manifests lane: the two source sets, the
#: Python signals, the foreign test owners and the project-manifest order);
#: 19 (the package-root marker set); 18 (the plan-gated root files).
#: 2026-10-07 (the dependency-directory lane): 12 (the shared set, the
#: fingerprint, the non-git fallback, both router walks and the probe derive
#: their dependency half; the two remainders that still spell ``.venv`` and the
#: two import fallbacks are marked, each with its reason).
_PENDING_CEILING = 12

#: The sites carrying a purpose-scoped marker, by owner. A marker is an
#: exemption, so each one shows up here as a test-file diff a reviewer reads,
#: never as a comment alone. The dependency-directory lane adds the
#: purpose-scoped lists its scope-out names.
_MARKED_SITES: frozenset[str] = frozenset({
    # The package-build staging list that landed on main beside this lane: the
    # names this repository's own sdist never ships, held to MANIFEST.in and
    # .gitignore by tests/test_artifact_parity.py (2026-10-06).
    "espalier/artifact_parity.py::BUILD_TREE_SKIP_NAMES",
    # The hook layer's pinned copies of its two projections, run on when the
    # deployed table cannot be read; held equal to the table below.
    "tools/cc/hooks/_hook_utils.py::_SOURCE_LANGUAGE_FALLBACK",
    "tools/cc/hooks/_hook_utils.py::_PROJECT_MANIFEST_FALLBACK",
    "tools/cc/hooks/_hook_utils.py::_STACK_ROOT_FALLBACK",
    # The package-root markers: a per-manifest flag the table does not carry,
    # held equal to its intersection with the table's manifests.
    "espalier/analyze.py::_PACKAGE_ROOT_MARKERS",
    # The dependency-directory lane (4-A): the two walkers whose local
    # remainder still spells ``.venv`` once their dependency half derives (a
    # Python environment is the adopter's own tooling, never a table member),
    # and the two tools/cc walkers' import fallbacks, held equal to the table
    # below.
    "espalier/analyze.py::_LOCAL_SKIP_PARTS",
    "espalier/repo_mode.py::_LOCAL_WALK_SKIP_DIRS",
    "tools/cc/reflect_protocol.py::_TABLE_PRUNE_FALLBACK",
    "tools/cc/sister_site_probe.py::_DEPENDENCY_DIRS_FALLBACK",
})


def _unmarked_by_owner() -> Counter:
    return Counter(f"{s.rel}::{s.owner}" for s in literal_sites() if not s.marked)


class TestEveryHandListIsDerivedOrMarked:
    """The ratchet. A hand list of stack vocabulary in the shipped roots is
    either a projection of the table (and then no literal spells it), marked
    purpose-scoped with a reason, or a baseline site still pending. It reads
    the same walker the ledger probe runs (tests/_stack_census.py)."""

    def test_the_walk_reads_the_shipped_roots(self):
        files = {rel for rel, _ in production_files()}
        assert "espalier/analyze.py" in files and "tools/cc/hooks/_hook_utils.py" in files
        assert not any(rel.startswith("espalier/_vendor/") for rel in files)
        assert not files & TABLE_FILES

    def test_no_new_hand_list_spells_stack_vocabulary(self):
        found = _unmarked_by_owner()
        new = {k: n for k, n in found.items() if n > _PENDING_SITES.get(k, 0)}
        assert not new, (
            "a collection literal spells stack vocabulary by hand: "
            f"{sorted(new)}. Derive it from tools/cc/_stack_table.py (the engine reads "
            "espalier/_stack_table.py), or mark it `# stack-table: ok purpose-scoped -- "
            "<why its purpose is not the stack's>` on its line or in the comment lines "
            "directly above, and name it in _MARKED_SITES."
        )

    def test_the_baseline_only_shrinks(self):
        """An entry whose site was derived or marked is deleted here, so the
        baseline is the live list of pending sites and never a stale allowance;
        and the baseline never grows past its dated ceiling."""
        found = _unmarked_by_owner()
        stale = {k: n for k, n in _PENDING_SITES.items() if found.get(k, 0) < n}
        assert not stale, (
            f"baseline entries no longer spelled by hand: {sorted(stale)} -- delete "
            "them from _PENDING_SITES and lower _PENDING_CEILING (the baseline only shrinks)"
        )
        assert sum(_PENDING_SITES.values()) <= _PENDING_CEILING, (
            "the baseline grew past its ceiling: a new hand list is not a pending site"
        )

    def test_the_ledger_probe_counts_the_same_sites(self):
        """The ledger probe prints ``unmarked_count()``; with the baseline as
        the only unmarked sites, the two agree by construction."""
        assert unmarked_count() == sum(_unmarked_by_owner().values())

    def test_every_marker_is_named_and_carries_a_reason(self):
        marked = {f"{s.rel}::{s.owner}" for s in literal_sites() if s.marked}
        assert marked == set(_MARKED_SITES), (
            f"marked sites changed: added {sorted(marked - _MARKED_SITES)}, "
            f"removed {sorted(_MARKED_SITES - marked)} -- a marker is an exemption; "
            "name each in _MARKED_SITES"
        )

    def test_every_marker_sits_on_a_list_that_spells_the_vocabulary(self):
        """A marker beside no such list (a projection, or a list emptied of the
        vocabulary) is stale: it would exempt the next hand list written in its
        place. And a marker states its reason."""
        covered = {(s.rel, n) for s in literal_sites() if s.marked for n in s.covers}
        stale = []
        for rel, path in production_files():
            for number, text in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
                if not MARKER_COMMENT.search(text):
                    continue
                if not MARKER_WITH_REASON.search(text):
                    stale.append(f"{rel}:{number} (no `-- <reason>`)")
                elif (rel, number) not in covered:
                    stale.append(f"{rel}:{number}")
        assert not stale, f"stack-table markers with no hand list beside them: {stale}"


def _sites_of(source: str, tmp_path: Path) -> list[Site]:
    root = tmp_path / "scratch"
    (root / "espalier").mkdir(parents=True)
    (root / "tools" / "cc").mkdir(parents=True)
    (root / "espalier" / "mod.py").write_bytes(source.encode("utf-8"))
    return literal_sites(vocabulary(), root=root)


class TestTheRatchetReadsEveryLiteralShape:
    """The ratchet is only as wide as the shapes it reads, and a marker only as
    narrow as the lines it covers."""

    @pytest.mark.parametrize("source", [
        '_X = {"node_modules", "dist"}',
        '_X = frozenset(["dist", ".pnpm-store"])',
        '_X = ("a",) + ("node_modules",)',
        '_X = "dist node_modules".split()',
        '_X = {"pyproject.toml": 1, "go.mod": 2}',
        '_X = (".py", ".mjs")',
        '_X = ["bun.lockb"]',
        '_X = {"a": ("node_modules",)}',
    ])
    def test_a_hand_list_in_any_shape_is_found(self, source, tmp_path):
        assert _sites_of(source, tmp_path), source

    @pytest.mark.parametrize("source", [
        '_X = {"dist", "build"}',
        '_X = (".py",)',
        '_X = ["package.json"]',
    ])
    def test_a_list_without_the_vocabulary_is_not(self, source, tmp_path):
        assert not _sites_of(source, tmp_path), source

    @pytest.mark.parametrize("source", [
        '_X = ("target", "dist")',
        '_X = {"file": "a", "target": "b"}',
    ])
    def test_a_build_output_name_alone_is_not_a_trigger(self, source, tmp_path):
        """A known gap, kept on purpose: ``target`` is also an English word,
        and as a trigger it found three dict keys and field names for every
        real build-output list (measured; tests/_stack_census.py's docstring).
        The floor pin keeps ``target`` in the table either way."""
        assert not _sites_of(source, tmp_path), source

    def test_a_trailing_marker_covers_its_own_line_only(self, tmp_path):
        sites = _sites_of(
            '_A = {"node_modules", "dist"}  # stack-table: ok purpose-scoped -- a\n'
            '_B = {".venv", "bower_components", "build"}\n',
            tmp_path,
        )
        assert [(s.owner, s.marked) for s in sites] == [("_A", True), ("_B", False)]

    def test_a_comment_block_above_covers_the_literal_below_it(self, tmp_path):
        sites = _sites_of(
            "# stack-table: ok purpose-scoped -- a deletion-safety roster, not a\n"
            "#   prune list: a pruned name is not a deletable one\n"
            '_A = ("node_modules", "dist")\n'
            "\n"
            '_B = ("node_modules", "dist")\n',
            tmp_path,
        )
        assert [(s.owner, s.marked) for s in sites] == [("_A", True), ("_B", False)]

    def test_prose_naming_the_marker_marks_nothing(self, tmp_path):
        sites = _sites_of(
            '"""Lists carry a stack-table: ok purpose-scoped marker."""\n'
            '_A = ("node_modules", "dist")\n',
            tmp_path,
        )
        assert [(s.owner, s.marked) for s in sites] == [("_A", False)]


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


# ── Package-manager resolution and the commands it names ────────────────────

#: Bun 1.2's text lockfile, the shape `bun install` writes (JSONC).
_BUN_LOCK = (
    "{\n"
    '  "lockfileVersion": 1,\n'
    '  "workspaces": {\n'
    '    "": {\n'
    '      "name": "demo-web",\n'
    "    },\n"
    "  },\n"
    '  "packages": {},\n'
    "}\n"
)


def _node_tree(tmp_path: Path, files: dict[str, str], package_manager: str | None = None) -> Path:
    from _stack_trees import write_stack

    root = write_stack(tmp_path / "repo", "adopter-node")
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body.encode("utf-8"))
    if package_manager is not None:
        import json

        manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
        manifest["packageManager"] = package_manager
        (root / "package.json").write_bytes(json.dumps(manifest).encode("utf-8"))
    return root


class TestThePackageManagerIsReadFromTheRepository:
    """`analyze.detect_package_manager`: `packageManager` first, then the one
    lockfile at the root, then npm. Two managers' lockfiles name themselves
    rather than being guessed between. Before it, every Node tree was npm."""

    @pytest.mark.parametrize(("files", "declared", "expected"), [
        ({}, None, ("npm", "default")),
        ({"package-lock.json": '{"lockfileVersion": 3}\n'}, None, ("npm", "package-lock.json")),
        ({"npm-shrinkwrap.json": '{"lockfileVersion": 3}\n'}, None, ("npm", "npm-shrinkwrap.json")),
        ({"pnpm-lock.yaml": "lockfileVersion: '9.0'\n"}, None, ("pnpm", "pnpm-lock.yaml")),
        ({"yarn.lock": "# yarn lockfile v1\n"}, None, ("yarn", "yarn.lock")),
        ({"bun.lock": _BUN_LOCK}, None, ("bun", "bun.lock")),
        ({"bun.lockb": "bun"}, None, ("bun", "bun.lockb")),
        ({"bun.lock": _BUN_LOCK, "bun.lockb": "bun"}, None, ("bun", "bun.lock")),
        ({"pnpm-lock.yaml": "lockfileVersion: '9.0'\n"}, "yarn@4.5.0", ("yarn", "packageManager")),
        ({}, "pnpm@9.12.0+sha224.0123456789abcdef", ("pnpm", "packageManager")),
        ({"yarn.lock": "# yarn lockfile v1\n"}, "deno@2.0.0", ("yarn", "yarn.lock")),
        (
            {"pnpm-lock.yaml": "lockfileVersion: '9.0'\n", "package-lock.json": "{}\n"},
            None,
            ("npm", "ambiguous: package-lock.json, pnpm-lock.yaml"),
        ),
        ({"packages/web/pnpm-lock.yaml": "lockfileVersion: '9.0'\n"}, None, ("npm", "default")),
    ], ids=[
        "no-lockfile", "package-lock", "shrinkwrap", "pnpm", "yarn", "bun-text", "bun-binary",
        "bun-both-formats", "packageManager-wins", "packageManager-hash", "unknown-manager",
        "ambiguous", "nested-lockfile-is-not-the-roots",
    ])
    def test_the_manager_and_what_said_so(self, tmp_path, files, declared, expected):
        from espalier.analyze import detect_package_manager

        root = _node_tree(tmp_path, files, declared)
        assert detect_package_manager(root) == expected

    def test_a_repository_with_no_package_json_has_no_package_manager(self, tmp_path):
        from _stack_trees import write_stack
        from espalier.analyze import detect_package_manager

        root = write_stack(tmp_path / "repo", "adopter-python")
        (root / "pnpm-lock.yaml").write_bytes(b"lockfileVersion: '9.0'\n")
        assert detect_package_manager(root) == ("", "")

    def test_the_fingerprint_records_it(self, tmp_path):
        from espalier.analyze import fingerprint_repo

        root = _node_tree(tmp_path, {"pnpm-lock.yaml": "lockfileVersion: '9.0'\n"})
        fp = fingerprint_repo(root)
        assert fp.package_manager == {"name": "pnpm", "source": "pnpm-lock.yaml"}
        assert fp.to_dict()["package_manager"] == fp.package_manager

    def test_a_python_fingerprint_records_none(self, tmp_path):
        from _stack_trees import write_stack
        from espalier.analyze import fingerprint_repo

        assert fingerprint_repo(write_stack(tmp_path / "repo", "adopter-python")).package_manager == {}


class TestTheCommandsRunUnderTheRepositorysManager:
    """`detect_tests` and `detect_actions` spell each script under the
    manager the repository uses, from the table's argv templates."""

    @pytest.mark.parametrize(("lockfile", "test", "lint", "build"), [
        (None, "npm test", "npm run lint", "npm run build"),
        ("pnpm-lock.yaml", "pnpm test", "pnpm run lint", "pnpm run build"),
        ("yarn.lock", "yarn test", "yarn run lint", "yarn run build"),
        # `bun test` is Bun's own runner, not the manifest's script.
        ("bun.lock", "bun run test", "bun run lint", "bun run build"),
    ], ids=["npm", "pnpm", "yarn", "bun"])
    def test_test_lint_and_build(self, tmp_path, lockfile, test, lint, build):
        from espalier.analyze import detect_actions, detect_tests

        root = _node_tree(tmp_path, {lockfile: _BUN_LOCK} if lockfile else {})
        tests = detect_tests(root)
        actions = detect_actions(root, tests)
        assert tests == [test]
        assert (actions["test"], actions["lint"], actions["build"]) == ([test], [lint], [build])

    @pytest.mark.parametrize(("lockfile", "start"), [
        (None, "npm start"),
        ("pnpm-lock.yaml", "pnpm start"),
        ("yarn.lock", "yarn start"),
        ("bun.lock", "bun run start"),
    ], ids=["npm", "pnpm", "yarn", "bun"])
    def test_the_start_script_is_the_smoke(self, tmp_path, lockfile, start):
        import json

        from espalier.analyze import detect_actions

        root = _node_tree(tmp_path, {lockfile: _BUN_LOCK} if lockfile else {})
        manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
        manifest["scripts"]["start"] = "node src/index.mjs"
        (root / "package.json").write_bytes(json.dumps(manifest).encode("utf-8"))
        assert detect_actions(root, [])["smoke"] == [start]

    def test_the_npm_strings_are_the_ones_inferred_before_the_table(self, tmp_path):
        """Equality first: with no lockfile every string is byte-equal to the
        literal the engine spelled before it read the table."""
        import json

        from _stack_trees import write_stack
        from espalier.analyze import detect_actions, detect_tests

        root = write_stack(tmp_path / "repo", "node")
        assert detect_tests(root) == ["npm test"]
        assert detect_actions(root, ["npm test"])["build"] == ["npm run build"]
        assert detect_actions(root, ["npm test"])["smoke"] == ["npm run dev"]
        manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
        del manifest["scripts"]["dev"]
        manifest["scripts"]["start"] = "node ."
        (root / "package.json").write_bytes(json.dumps(manifest).encode("utf-8"))
        assert detect_actions(root, [])["smoke"] == ["npm start"]

    def test_go_and_rust_runners_come_from_their_rows(self, tmp_path):
        from _stack_trees import write_stack
        from espalier.analyze import detect_tests

        assert detect_tests(write_stack(tmp_path / "go", "adopter-go")) == ["go test ./..."]
        assert detect_tests(write_stack(tmp_path / "rust", "adopter-rust")) == ["cargo test"]



# ── Permission rules from the table ──────────────────────────────────────────


def _manager_names() -> list[str]:
    from espalier import _stack_table as table

    return [pm.name for pm in table.package_managers()]


class TestThePermissionRulesComeFromTheTable:
    """`settings_profiles._SCRIPT_RUNNERS` and `PYTHON_ONLY_ALLOWS` are
    projections of the table, and `narrowed_rules` stays the one narrowing
    function: the table carries argv, never a rule for a command."""

    def test_the_script_runners_are_the_tables_package_managers(self):
        from espalier import _stack_table as table
        from espalier import settings_profiles

        assert settings_profiles._SCRIPT_RUNNERS == table.script_runners()
        # equality with the hand list the projection replaced
        assert settings_profiles._SCRIPT_RUNNERS == frozenset({"npm", "pnpm", "yarn", "bun"})

    def test_the_python_only_rules_are_the_python_rows(self):
        from espalier import _stack_table as table
        from espalier import settings_profiles

        assert settings_profiles.PYTHON_ONLY_ALLOWS == frozenset(table.stack("python").static_allows)
        # equality with the hand list the projection replaced
        assert settings_profiles.PYTHON_ONLY_ALLOWS == frozenset({
            "Bash(pytest *)", "Bash(python -m pytest *)", "Bash(python3 -m pytest *)",
            "Bash(ruff *)", "Bash(black *)",
        })

    def test_only_the_python_row_carries_static_allows(self):
        """A profile has ONE python_only filter keyed on a Python fingerprint,
        so a second row's rules would ship on Python trees or nowhere. Decide
        that wiring before adding them."""
        from espalier import _stack_table as table

        assert [row.name for row in table.STACKS if row.static_allows] == ["python"]

    def test_every_filtering_profile_carries_the_rows_rules(self):
        """`python_only` only filters a profile's allow list at render, so a
        rule in the row and not in the list would render nowhere."""
        from espalier import _stack_table as table
        from espalier import settings_profiles

        rules = set(table.stack("python").static_allows)
        filtering = [p for p in settings_profiles.PROFILES.values() if p.python_only]
        assert filtering, "no profile filters the Python rules -- the pin reads nothing"
        for profile in filtering:
            assert profile.python_only == rules
            assert rules <= set(profile.allow), profile

    def test_a_python_fingerprint_is_read_from_the_python_row(self):
        from espalier.settings_profiles import is_python_fingerprint

        assert is_python_fingerprint({"languages": ["typescript", "python"]})
        assert not is_python_fingerprint({"languages": ["javascript", "astro"]})
        assert not is_python_fingerprint({"languages": [{"not": "a name"}]})
        assert not is_python_fingerprint(None)

    @pytest.mark.parametrize("name", _manager_names())
    def test_no_template_derives_a_bare_rule(self, name):
        from espalier import _stack_table as table
        from espalier.settings_profiles import narrowed_rules

        pm = table.package_manager(name)
        assert pm is not None
        for argv in (pm.test, (*pm.run, "build"), pm.start):
            rules = narrowed_rules(" ".join(argv))
            assert rules, argv
            assert f"Bash({name} *)" not in rules, (argv, rules)
            assert f"Bash({' '.join(pm.run)} *)" not in rules, (argv, rules)
        assert narrowed_rules(" ".join((*pm.run, "build"))) == [
            f"Bash({' '.join(pm.run)} build)", f"Bash({' '.join(pm.run)} build *)",
        ]

    @pytest.mark.parametrize("name", _manager_names())
    @pytest.mark.parametrize("verb", ["exec", "dlx"])
    def test_an_executor_verb_derives_the_exact_form_only(self, name, verb):
        from espalier.settings_profiles import narrowed_rules

        assert narrowed_rules(f"{name} {verb} x") == [f"Bash({name} {verb} x)"]

    def test_a_pnpm_tree_is_granted_pnpm_and_not_npm(self, tmp_path):
        from _stack_trees import write_stack
        from espalier.analyze import fingerprint_repo
        from espalier.settings_profiles import _workflow_fingerprint_allows

        fp = fingerprint_repo(write_stack(tmp_path / "repo", "adopter-node-pnpm")).to_dict()
        rules = set(_workflow_fingerprint_allows(fp))
        assert {
            "Bash(pnpm test)", "Bash(pnpm test *)",
            "Bash(pnpm run lint)", "Bash(pnpm run lint *)",
            "Bash(pnpm run build)", "Bash(pnpm run build *)",
        } <= rules
        assert not {r for r in rules if r.startswith("Bash(npm ")}, rules
        assert not {"Bash(pnpm run)", "Bash(pnpm run *)", "Bash(pnpm *)"} & rules, rules


# ── /preflight's fallback lint ladder, pinned to the table ──────────────────

_PREFLIGHT = REPO / "espalier" / "assets" / "claude" / "commands" / "preflight.md"
_BRANCH = re.compile(r"^(?:el)?if (?P<guard>.+?); then\n\s+(?P<command>.+?) \|\| exit 1$", re.M)
_FILE_TEST = re.compile(r"\[ -f (?P<name>[^\s\]]+) \]")


def _lint_ladder(body: str) -> list[tuple[frozenset[str], str]]:
    """``(files the guard tests, command)`` for each guarded fallback branch of
    Step 1's bash fence: the probes that run only when nothing is declared."""
    fence = re.findall(r"```bash\n(.*?)```", body, re.S)[0]
    # The ladder is the one if/elif chain that opens on the declared command;
    # a later `if` in the fence (the self-host type gate) is not part of it.
    chain = re.search(r'^if \[ -n "\$LINT" \]; then\n.*?^fi$', fence, re.S | re.M)
    assert chain, "Step 1's declared-lint chain moved; re-anchor the ladder reader"
    ladder = []
    for match in _BRANCH.finditer(chain.group(0)):
        files = frozenset(m.group("name") for m in _FILE_TEST.finditer(match.group("guard")))
        if files:
            ladder.append((files, match.group("command").strip()))
    return ladder


def _ladder_mismatches(body: str) -> list[str]:
    """Each table stack with a fallback lint needs a branch guarded by one of
    its manifests that runs that lint; each guarded branch must be a table
    stack's, guarded by that stack's manifests only."""
    from espalier import _stack_table as table

    ladder = _lint_ladder(body)
    wrong = []
    for row in table.STACKS:
        if not row.lint_fallback:
            continue
        command = " ".join(row.lint_fallback)
        if not any(command == cmd and files & set(row.manifests) for files, cmd in ladder):
            wrong.append(f"{row.name}: no branch guarded by {list(row.manifests)} runs `{command}`")
    by_command = {" ".join(r.lint_fallback): r for r in table.STACKS if r.lint_fallback}
    for files, command in ladder:
        row = by_command.get(command)
        if row is None:
            wrong.append(f"a branch guarded by {sorted(files)} runs `{command}`, no table stack's lint")
        elif not files <= set(row.manifests) | {"node_modules/.bin/eslint"}:
            wrong.append(f"`{command}` is guarded by {sorted(files - set(row.manifests))}, "
                         f"not {row.name}'s manifests")
    return wrong


class TestThePreflightLadderIsTheTables:
    """`/preflight` Step 1's fallback ladder stays bash (the operator's call:
    a runtime read would move `command -v` into `shutil.which`, which resolves
    differently on Windows). It is pinned to the table both ways instead."""

    def test_the_runners_exclude_is_the_tables_word(self):
        """`harness_config.VENDORED_RUFF_EXCLUDE` (the inferred lint line's
        exclude and init's ruff note, DEF-1154) and the Python row's fallback
        name one tree; the day either moves, this reds with both names."""
        from espalier import _stack_table as table
        from espalier.harness_config import VENDORED_RUFF_EXCLUDE
        fallback = table.stack("python").lint_fallback
        assert fallback[fallback.index("--extend-exclude") + 1] == VENDORED_RUFF_EXCLUDE, (fallback, VENDORED_RUFF_EXCLUDE)

    def test_the_deployed_ladder_matches_the_table(self):
        assert _lint_ladder(_PREFLIGHT.read_text(encoding="utf-8")), "no guarded branch was read"
        assert _ladder_mismatches(_PREFLIGHT.read_text(encoding="utf-8")) == []

    def test_a_deleted_branch_reds(self):
        body = _PREFLIGHT.read_text(encoding="utf-8")
        branch = re.search(r"^elif \[ -f go\.mod \].*?\n.*?\n", body, re.M)
        assert branch, "the go.mod branch moved; the mutation needs re-anchoring"
        mutated = body.replace(branch.group(0), "", 1)
        assert any(line.startswith("go:") for line in _ladder_mismatches(mutated))

    def test_a_branch_the_table_does_not_know_reds(self):
        body = _PREFLIGHT.read_text(encoding="utf-8").replace(
            "golangci-lint run ./...", "golangci-lint run --fast ./...", 1,
        )
        assert _ladder_mismatches(body), "a changed fallback command went unseen"


# ── The hand lists the source-and-manifests lane derived ─────────────────────


def _load_hook_utils(name: str = "_hook_utils_under_stack_table_test"):
    """``tools/cc/hooks/_hook_utils.py`` loaded by path, as the hooks load it."""
    path = REPO / "tools" / "cc" / "hooks" / "_hook_utils.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class TestTheSourceAndManifestListsAreProjections:
    """3-A, 3-B and 3-D of the stack-registry pack: the hook and engine hand
    lists of source suffixes and manifests read the table, equal to the
    literals they replaced. Each replaced literal is held here once; a pin on
    a value a widening moves is deleted in that widening's commit."""

    def test_the_hook_source_set_is_the_table(self):
        from espalier import _stack_table as table

        hook_utils = _load_hook_utils()
        assert hook_utils._STACK_TABLE_FAULT is None
        assert hook_utils.SOURCE_LANGUAGE_EXTENSIONS == table.source_extensions()
        assert hook_utils.SOURCE_LANGUAGE_EXTENSIONS == frozenset({
            ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", ".mts", ".cts",
            ".astro", ".vue", ".svelte", ".go", ".rs", ".java", ".rb", ".php",
            ".cpp", ".c", ".h", ".cs", ".swift", ".kt", ".scala",
        })

    def test_the_fingerprint_map_is_the_tables_projection(self):
        """Order is read: the map keeps the table's row order. Since Decision
        5's widening the map holds every source suffix the hooks gate, so the
        three the fingerprint used to leave out (``.h``, ``.scala``,
        ``.swift``) read as languages too."""
        from espalier import _stack_table as table
        from espalier.analyze import SUFFIX_TO_LANGUAGE

        assert list(SUFFIX_TO_LANGUAGE.items()) == list(table.suffix_to_language().items())
        assert set(SUFFIX_TO_LANGUAGE) == table.source_extensions()
        assert {SUFFIX_TO_LANGUAGE[s] for s in (".h", ".scala", ".swift")} == {"c", "scala", "swift"}

    def test_the_manifest_lists_are_projections(self):
        from espalier import _stack_table as table
        from espalier import analyze

        hook_utils = _load_hook_utils()
        owners = table.stacks_with_a_test_command()
        assert [row.name for row in owners] == ["python", "node", "go", "rust"]
        # A test-owning row with no manifest would index an empty tuple in the
        # hook layer's guarded read and put every hook on the pinned copy.
        assert all(row.manifests for row in owners), [row.name for row in owners if not row.manifests]
        assert hook_utils.PROJECT_MANIFEST_NAMES == tuple(row.manifests[0] for row in owners)
        # The read order moved go.mod ahead of Cargo.toml: repo_name reads no
        # name out of go.mod (it has no `name` line), so no name moves.
        assert hook_utils.PROJECT_MANIFEST_NAMES == (
            "pyproject.toml", "package.json", "go.mod", "Cargo.toml",
        )
        assert analyze._PYTHON.manifests == (
            "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "Pipfile",
        )
        assert set(analyze._FOREIGN_TEST_OWNERS) == {"package.json", "go.mod", "Cargo.toml"}
        # The provider derives from the same rows as the suppressor: a row
        # that gains a test runner gains both. Row order: go before rust.
        assert list(analyze._STACK_TEST_BY_MANIFEST.items()) == [
            ("go.mod", ("go", "test", "./...")), ("Cargo.toml", ("cargo", "test")),
        ]
        # The package-root markers are the six they have always been, held as
        # a filter on the table (a marked list: the table has no per-manifest
        # flag for "marks a package root"); any subtraction or widening reds
        # here by name.
        assert analyze.MANIFEST_NAMES == analyze._PACKAGE_ROOT_MARKERS
        assert analyze.MANIFEST_NAMES == frozenset(table.manifest_names()) & analyze._PACKAGE_ROOT_MARKERS
        assert analyze.MANIFEST_NAMES == {
            "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
        }

    def test_the_fallbacks_equal_the_table_and_are_never_empty(self):
        """Each pinned copy is compared to the TABLE, never to the projection
        it stands in for: under the fault it guards the two are one object,
        and `x == x` proves nothing (lane B's review)."""
        from espalier import _stack_table as table

        hook_utils = _load_hook_utils()
        assert hook_utils._STACK_TABLE_FAULT is None, hook_utils._STACK_TABLE_FAULT
        assert hook_utils._SOURCE_LANGUAGE_FALLBACK == table.source_extensions()
        assert hook_utils._PROJECT_MANIFEST_FALLBACK == tuple(
            row.manifests[0] for row in table.stacks_with_a_test_command()
        )
        assert hook_utils._STACK_ROOT_FALLBACK == (
            frozenset(table.manifest_names()) | frozenset(table.lockfile_owners())
        )
        assert hook_utils._SOURCE_LANGUAGE_FALLBACK and hook_utils._PROJECT_MANIFEST_FALLBACK
        assert hook_utils._STACK_ROOT_FALLBACK

    def test_the_plan_gated_root_files_are_every_manifest_and_lockfile(self):
        """3-C: the table's manifests and lockfiles, and nothing of the table
        left out -- a lockfile added to a package manager is plan-gated the
        day it is added."""
        from espalier import _stack_table as table

        hook_utils = _load_hook_utils()
        assert hook_utils.STACK_ROOT_FILES == (
            frozenset(table.manifest_names()) | frozenset(table.lockfile_owners())
        )
        assert {"go.mod", "go.sum", "Gemfile", "bun.lockb", "Pipfile"} <= hook_utils.STACK_ROOT_FILES

    def test_the_scannable_flag_names_the_python_row_alone(self):
        from espalier import _stack_table as table

        assert table.scannable_languages() == frozenset({"python"})
        assert [row.name for row in table.STACKS if row.ast_scannable] == ["python"]

    def test_verify_pins_reads_the_projection_from_a_scratch_checkout(self, tmp_path):
        """The pin checker loads _hook_utils.py by path from a checkout and must
        read a set EQUAL to the table's -- never an empty one, the collapse its
        own docstring forbids, and never None, which it prints as unavailable."""
        from espalier import _stack_table as table

        spec = importlib.util.spec_from_file_location(
            "_verify_pins_for_stack_table", REPO / "scripts" / "verify_pins.py",
        )
        assert spec is not None and spec.loader is not None
        verify_pins = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = verify_pins  # a dataclass resolves its module through sys.modules on 3.14
        spec.loader.exec_module(verify_pins)
        checkout = tmp_path / "checkout"
        for rel in ("tools/cc/hooks/_hook_utils.py", "tools/cc/_stack_table.py", "tools/cc/_json_safe.py"):
            dest = checkout / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, dest)
        assert verify_pins.source_language_extensions(checkout) == table.source_extensions()


_PLAN_GUARD_WRITE = {
    "hook_event_name": "PreToolUse", "tool_name": "Write",
    "tool_input": {"file_path": "app.py", "content": "x = 1\n"},
}

#: Three ways a deployed table fails the hook layer: gone, hand-patched into a
#: SyntaxError, and older than the hooks that read it (no projection helper).
_TABLE_FAULTS: dict[str, str | None] = {
    "missing": None,
    "syntax-error": "def (\n",
    "older-than-the-hooks": "STACKS = ()\n\n\ndef source_extensions():\n    return frozenset({'.py'})\n",
}


def _deployed_copy(tmp_path: Path) -> Path:
    """tools/cc as init deploys it, under a scratch project root."""
    root = tmp_path / "project"
    shutil.copytree(
        REPO / "tools" / "cc", root / "tools" / "cc",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return root


def _load_tools_cc_script(name: str, alias: str):
    """A tools/cc script loaded by path with tools/cc resolvable for its
    sibling imports (``_json_safe``, the table) while it executes."""
    tools_cc = REPO / "tools" / "cc"
    added = str(tools_cc) not in sys.path
    if added:
        sys.path.insert(0, str(tools_cc))
    try:
        spec = importlib.util.spec_from_file_location(alias, tools_cc / name)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[alias] = module
        spec.loader.exec_module(module)
    finally:
        if added:
            sys.path.remove(str(tools_cc))
    return module


class TestTheDependencyDirectoryListsAreProjections:
    """4-A of the stack-registry pack: the shared set and the dependency half
    of five walkers' skip lists read the table. Each list is held to the
    table AND to the local remainder it keeps, so a name the table gains is
    pruned everywhere the day it lands and a local prune cannot go missing in
    silence; the two tools/cc fallbacks are compared to the TABLE, never to the
    projection they stand in for (lane B's review: ``x == x`` proves nothing)."""

    def test_the_shared_set_is_the_tables_dependency_directories(self):
        from espalier import _stack_table as table
        from espalier._safe_walk import DEPENDENCY_TREE_DIRS

        assert DEPENDENCY_TREE_DIRS == table.dependency_dirs()
        assert DEPENDENCY_TREE_DIRS == {
            "node_modules", "bower_components", "jspm_packages", ".yarn", ".pnpm-store",
        }

    def test_the_fingerprint_skips_the_tables_dependency_and_output_directories(self):
        """The widening 4-A is: the four Node names the fingerprint lacked
        (DEF-971's second half) are skipped from this commit on."""
        from espalier import _stack_table as table
        from espalier import analyze

        assert analyze.DEFAULT_SKIP_PARTS == (
            analyze._LOCAL_SKIP_PARTS | table.dependency_dirs() | table.output_dirs()
        )
        assert analyze._LOCAL_SKIP_PARTS == {
            ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
            ".ruff_cache", "dist", "build", "coverage", "htmlcov", ".next",
        }
        assert {"bower_components", "jspm_packages", ".yarn", ".pnpm-store", "target"} <= analyze.DEFAULT_SKIP_PARTS

    def test_the_non_git_fallback_prunes_the_dependency_half_only(self):
        """Build output stays walked there by design (a ``dist/`` the user
        built locally is still checked), so ``target`` is not a member."""
        from espalier import _stack_table as table
        from espalier import repo_mode

        assert repo_mode._WALK_SKIP_DIRS == repo_mode._LOCAL_WALK_SKIP_DIRS | table.dependency_dirs()
        assert repo_mode._LOCAL_WALK_SKIP_DIRS == {
            ".git", ".espalier", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
            ".venv", "venv", "env", ".idea", ".vscode",
        }
        assert not table.output_dirs() & repo_mode._WALK_SKIP_DIRS

    def test_both_router_walks_prune_the_tables_dependency_and_output_directories(self):
        from espalier import _stack_table as table
        from espalier import reflect_protocol as engine

        hook = _load_tools_cc_script("reflect_protocol.py", "_reflect_protocol_under_stack_table_test")
        local = frozenset({"__pycache__", "dist", "build", "site-packages", "venv"})
        expected = local | table.dependency_dirs() | table.output_dirs()
        assert engine._WALK_SKIP_DIRS == expected
        assert hook._WALK_SKIP_DIRS == expected
        assert hook._TABLE_PRUNE_FALLBACK == table.dependency_dirs() | table.output_dirs()
        assert hook._TABLE_PRUNE_FALLBACK

    def test_the_sister_site_probe_prunes_the_tables_dependency_directories(self):
        from espalier import _stack_table as table

        probe = _load_tools_cc_script("sister_site_probe.py", "_sister_site_probe_under_stack_table_test")
        local = frozenset({
            "__pycache__", "venv", "env", "site-packages", "build", "dist",
            "_vendor", "vendor", "vendored", "third_party", "tests", "test",
        })
        assert probe._ADOPTER_PRUNE_NAMES == local | table.dependency_dirs()
        assert probe._DEPENDENCY_DIRS_FALLBACK == table.dependency_dirs()
        assert probe._DEPENDENCY_DIRS_FALLBACK


# slow-exempt: three sub-second launches of the deployed plan_guard on a copied tools/cc (the unreadable-table drives below); the module stays in the fast slice
class TestTheHookLayerSurvivesAnUnreadableTable:
    """3-A's guard: the table is a single point of failure for every hook,
    since _hook_utils imports it and every hook imports _hook_utils. A
    deployed copy that cannot be read must leave the gates running on the
    pinned copy -- the same verdict, exit 0 -- and say so once a session."""

    @pytest.mark.parametrize("fault", sorted(_TABLE_FAULTS))
    def test_plan_guard_keeps_its_verdict_and_says_so(self, tmp_path, fault):
        root = _deployed_copy(tmp_path)
        table = root / "tools" / "cc" / "_stack_table.py"
        body = _TABLE_FAULTS[fault]
        if body is None:
            table.unlink()
        else:
            table.write_text(body, encoding="utf-8")
        audit = tmp_path / "audit"
        env = {k: v for k, v in os.environ.items() if k != "ESPALIER_MAINTENANCE_MODE"}
        env["CLAUDE_PROJECT_DIR"] = str(root)
        env["ESPALIER_AUDIT_DIR"] = str(audit)
        proc = subprocess.run(
            [sys.executable, str(root / "tools" / "cc" / "hooks" / "plan_guard.py")],
            input=json.dumps({"cwd": str(root), **_PLAN_GUARD_WRITE}),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(root), env=env, timeout=60,
        )
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        verdict = json.loads(proc.stdout)["hookSpecificOutput"]
        assert verdict["permissionDecision"] == "deny", proc.stdout
        reason = verdict.get("permissionDecisionReason", "")
        assert "plan" in reason.lower() and "crash" not in reason.lower(), reason
        assert "_stack_table.py could not be read" in proc.stderr, proc.stderr
        records = [
            json.loads(line)
            for log in audit.glob("*.log")
            for line in log.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        said = [r for r in records if r.get("event_type") == "hook_layer_failed_open_stack_table"]
        assert len(said) == 1 and said[0]["details"]["hook"] == "plan_guard", records

    def test_the_live_tree_reads_its_table(self):
        hook_utils = _load_hook_utils("_hook_utils_live_table")
        assert hook_utils._STACK_TABLE is not None and hook_utils._STACK_TABLE_FAULT is None
