"""The stack table (``tests/_stack_trees.py``), the fixtures that write it, and
the builder that takes a stack (``tests/_adopter_tree.py::build_adopter_tree``).

The six portable stack fixtures used to be hand-written bodies in
``tests/conftest.py``. They are now ``write_stack`` calls on the table's fixture
rows, and the selfcheck mirror carries a byte copy of the table. The rows were
proven equal to the old bodies before the fold, and these tests keep each
fixture writing exactly its row, the same bytes on every host.

``build_adopter_tree`` takes a stack and a depth. At the full depth (``init``
and ``install-ci``) it runs once per stack per module, about 5 s a tree on the
Windows host.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from _adopter_tree import TREE_DEPTHS, build_adopter_tree
from _stack_trees import ADOPTER_PREFIX, ADOPTER_STACKS, STACKS, write_stack

REPO_ROOT = Path(__file__).resolve().parent.parent

# Fixture -> its row. The selfcheck mirror carries exactly these six.
_FIXTURE_ROWS = {
    "python_repo": "python",
    "ml_repo": "ml",
    "node_repo": "node",
    "typescript_repo": "typescript",
    "go_repo": "go",
    "polyglot_repo": "polyglot",
}

# The language the fingerprint should report for each adopter stack.
_LANGUAGE = {
    "python": "python", "node": "javascript", "node-pnpm": "javascript", "go": "go",
    "rust": "rust",
}
_MJS_UNREAD = pytest.mark.xfail(
    strict=True,
    reason=(
        "DEF-961: espalier/analyze.py::SUFFIX_TO_LANGUAGE has no .mjs or .astro, so a Node "
        "project written in them reads as no language at all"
    ),
)


def _snapshot(root: Path) -> tuple[dict[str, bytes], set[str]]:
    """The files under ``root`` (bytes) and its empty directories (with a
    trailing ``/``), ``.git`` excluded."""
    files: dict[str, bytes] = {}
    empty: set[str] = set()
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if rel == ".git" or rel.startswith(".git/"):
            continue
        if path.is_dir():
            if not any(path.iterdir()):
                empty.add(rel + "/")
        else:
            files[rel] = path.read_bytes()
    return files, empty


def _row(row: str) -> tuple[dict[str, bytes], set[str]]:
    body = STACKS[row]
    return (
        {rel: text.encode("utf-8") for rel, text in body.items() if not rel.endswith("/")},
        {rel for rel in body if rel.endswith("/")},
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout


class TestTheTableIsPortable:
    def test_the_table_imports_the_standard_library_only(self):
        # The selfcheck mirror runs beside an installed wheel, and the release
        # smoke may load the table by path: no espalier, no third party.
        tree = ast.parse((REPO_ROOT / "tests" / "_stack_trees.py").read_text(encoding="utf-8"))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                roots.add((node.module or "").split(".")[0])
        assert roots <= set(sys.stdlib_module_names) | {"__future__"}, sorted(roots)

    def test_every_key_is_a_relative_posix_path(self):
        bad = [
            f"{row}:{rel}" for row, body in STACKS.items() for rel in body
            if not rel or rel.startswith("/") or "\\" in rel or ".." in rel.split("/")
            or (rel.endswith("/") and body[rel] != "")
        ]
        assert not bad, bad

    def test_the_portable_fixtures_are_the_selfcheck_mirrors_six(self):
        # The sync script extracts these fixtures into the mirror conftest, so
        # the folded set and the mirrored set must be one set.
        spec = importlib.util.spec_from_file_location(
            "_sync_selfcheck_tests", REPO_ROOT / "scripts" / "sync_selfcheck_tests.py",
        )
        assert spec and spec.loader
        sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sync)
        assert set(sync._PORTABLE_FIXTURES) == set(_FIXTURE_ROWS)
        assert "_stack_trees.py" in sync.BYTE_MIRRORED

    def test_every_adopter_row_is_a_stack_the_builder_takes(self):
        rows = {name for name in STACKS if name.startswith(ADOPTER_PREFIX)}
        assert {ADOPTER_PREFIX + s for s in ADOPTER_STACKS} == rows
        assert set(_LANGUAGE) == set(ADOPTER_STACKS), (
            "a new adopter row needs the language its fingerprint should report"
        )

    def test_an_unknown_row_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="unknown stack row"):
            write_stack(tmp_path, "cobol")


class TestFixturesWriteTheirRow:
    @pytest.mark.parametrize("fixture,row", sorted(_FIXTURE_ROWS.items()))
    def test_the_fixture_tree_is_byte_identical_to_its_row(self, request, fixture, row):
        tree = request.getfixturevalue(fixture)
        assert (tree / ".git").is_dir(), "the fake .git marker cmd_init's pre-flight reads"
        files, empty = _snapshot(tree)
        # conftest's autouse `_isolate_audit_dir` makes `audit/` in every test's
        # tmp_path, the same one the fixtures write into; it is not the row's.
        assert (files, empty - {"audit/"}) == _row(row)


class TestBuildAdopterTree:
    @pytest.mark.parametrize("stack", ADOPTER_STACKS)
    def test_the_files_depth_writes_only_the_row(self, tmp_path, stack):
        root = build_adopter_tree(tmp_path, stack=stack, tree="files")
        assert not (root / ".git").exists()
        assert _snapshot(root) == _row(ADOPTER_PREFIX + stack)

    def test_the_git_depth_commits_the_row_on_the_named_branch(self, tmp_path):
        root = build_adopter_tree(tmp_path, stack="node", tree="git", branch="master")
        assert _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip() == "master"
        assert sorted(_git(root, "ls-files").split()) == sorted(_row("adopter-node")[0])
        assert _git(root, "status", "--porcelain") == ""
        assert not (root / ".claude").exists(), "the git depth must not run init"

    def test_the_default_is_the_python_tree_at_full_depth(self):
        import inspect

        params = inspect.signature(build_adopter_tree).parameters
        assert list(params)[:4] == ["dest", "stack", "tree", "branch"]
        defaults = {name: params[name].default for name in ("stack", "tree", "branch")}
        assert defaults == {"stack": "python", "tree": "adopter", "branch": "main"}
        assert TREE_DEPTHS == ("files", "git", "adopter")

    def test_an_unknown_stack_or_depth_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="unknown stack"):
            build_adopter_tree(tmp_path / "a", stack="cobol")
        with pytest.raises(ValueError, match="unknown depth"):
            build_adopter_tree(tmp_path / "b", tree="deep")


@pytest.fixture(scope="module")
def adopter_trees(tmp_path_factory):
    """One full-depth tree per stack, built on first use and shared by this
    module's tests only (read-only: no test here writes into one)."""
    cache: dict[str, Path] = {}

    def get(stack: str) -> Path:
        if stack not in cache:
            cache[stack] = build_adopter_tree(tmp_path_factory.mktemp(f"adopter-{stack}"), stack=stack)
        return cache[stack]

    return get


class TestEveryStackInstalls:
    @pytest.mark.parametrize("stack", ADOPTER_STACKS)
    def test_init_and_install_ci_run_on_every_stack(self, adopter_trees, stack):
        # build_adopter_tree raises when either verb exits non-zero or the
        # result is not an adopter tree; this asserts what is left on disk.
        root = adopter_trees(stack)
        assert (root / ".claude" / "settings.json").is_file()
        assert (root / ".github" / "workflows" / "harness-guard.yml").is_file()
        files, _ = _row(ADOPTER_PREFIX + stack)
        for rel, body in files.items():
            on_disk = (root / rel).read_bytes()
            if rel == ".gitignore":
                # init appends its own entries; the adopter's lines stay first.
                assert on_disk.startswith(body), on_disk[:200]
            else:
                assert on_disk == body, f"init rewrote the adopter's {rel}"

    @pytest.mark.parametrize(
        "stack",
        [pytest.param(s, marks=_MJS_UNREAD) if s.startswith("node") else s for s in ADOPTER_STACKS],
    )
    def test_the_fingerprint_reads_the_stack(self, adopter_trees, stack):
        root = adopter_trees(stack)
        fingerprint = json.loads(
            (root / "reports" / "repo_fingerprint.json").read_text(encoding="utf-8")
        )
        assert _LANGUAGE[stack] in fingerprint["languages"], fingerprint["languages"]
