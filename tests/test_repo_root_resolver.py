"""One repo-root resolver: the hooks, the top-level tools and the statusline
read ``CLAUDE_PROJECT_DIR`` through ``tools/cc/_paths.py::project_root_spelling``.

Before it, three spellings disagreed (DEF-664): ``_hook_utils`` translated a
Git Bash ``/c/...`` value and warned only on an empty one, while
``_paths._repo_root`` and ``statusline.main`` read the value raw and fell back
silently. A Windows adopter on Git Bash had a plan written under one root and
looked for under the other; a hook run by hand with the variable unset put its
state under whatever directory it started in, without a word.

The rows drive the real call chain on every host. The translator returns
early off Windows, so each translating row uses a stand-in that maps ``/c``
onto a real directory, and each pairs it with an identity swap that must give
the untranslated answer: a row that stops reaching the translator reads red on
its own, never green for nothing on a POSIX cell.
"""
# pytest-marker: default-unit
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_CC = REPO_ROOT / "tools" / "cc"
HOOKS_DIR = TOOLS_CC / "hooks"

sys.path.insert(0, str(TOOLS_CC))
import _paths  # noqa: E402


def _hook_utils():
    """The bare ``_hook_utils`` a hook process imports (``tests/CLAUDE.md``:
    patch the object the code under test reads)."""
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        import _hook_utils  # type: ignore
        return _hook_utils
    finally:
        sys.path.pop(0)


def _statusline():
    spec = importlib.util.spec_from_file_location("_statusline_root_rows", TOOLS_CC / "statusline.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _onto(drive: Path):
    """The stand-in translator: ``/c/...`` onto ``drive``, anything else unchanged."""
    anchor = drive.as_posix().rstrip("/")

    def to_dir(path: str) -> str:
        m = re.match(r"^/[cC](?=/|$)", path)
        return anchor + (path[2:] or "/") if m else path
    return to_dir


def _identity(path: str) -> str:
    return path


@pytest.fixture
def translating(monkeypatch):
    """Set the hooks' translator and force the Windows gate, so the top-level
    tools reach the same translator object the hooks pass in."""
    hu = _hook_utils()

    def use(translator):
        monkeypatch.setattr(hu, "_msys_drive_to_windows", translator)
        monkeypatch.setattr(_paths, "_ON_WINDOWS", True)
    return use


def _three_roots() -> list[Path]:
    hu = _hook_utils()
    return [hu.resolve_project_root(), _paths._repo_root(), _statusline()._project_root()]


class TestOneTranslation:
    def test_the_three_resolvers_agree_on_a_git_bash_value(self, tmp_path, monkeypatch, translating):
        drive = tmp_path / "drive"
        (drive / "repo").mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/c/repo")
        translating(_onto(drive))
        assert _three_roots() == [(drive / "repo").resolve()] * 3

    def test_with_the_translation_swapped_for_identity_none_lands_there(
            self, tmp_path, monkeypatch, translating):
        drive = tmp_path / "drive"
        (drive / "repo").mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/c/repo")
        translating(_identity)
        assert (drive / "repo").resolve() not in _three_roots()

    def test_a_native_value_is_never_handed_to_the_translator(self, tmp_path, monkeypatch, translating):
        """Only a POSIX-spelled value on Windows loads the hooks' translator."""
        seen: list[str] = []

        def record(path: str) -> str:
            seen.append(path)
            return path
        # A drive-spelled value on every host (on POSIX `str(tmp_path)` starts
        # with `/` and is handed over, rightly: the code review's first warning).
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "C:/proj")
        translating(record)
        assert _paths._repo_root() == Path("C:/proj").resolve()
        assert seen == []


class TestTheWalkUp:
    @staticmethod
    def _tree(tmp_path: Path, *marker: str) -> tuple[Path, Path]:
        root = tmp_path / "proj"
        root.joinpath(*marker).mkdir(parents=True)
        deep = root / "a" / "b"
        deep.mkdir(parents=True)
        return root, deep

    def test_an_unset_variable_walks_up_to_the_deploy_marker(self, tmp_path, monkeypatch, capsys):
        """A non-Python adopter's tree carries ``tools/cc/hooks`` and no
        ``pyproject.toml``; every resolver finds its root from a subdirectory,
        and says nothing, because the answer is right."""
        root, deep = self._tree(tmp_path, "tools", "cc", "hooks")
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(deep)
        assert _three_roots() == [root.resolve()] * 3
        assert "CLAUDE_PROJECT_DIR" not in capsys.readouterr().err

    def test_with_no_marker_above_it_falls_to_the_cwd_and_says_so(self, tmp_path, monkeypatch, capsys):
        root, deep = self._tree(tmp_path, "tools", "cc")   # no hooks/: not a deployed tree
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(deep)
        assert _three_roots() == [deep.resolve()] * 3
        assert "CLAUDE_PROJECT_DIR is unset" in capsys.readouterr().err

    def test_an_empty_variable_still_warns_and_then_walks_up(self, tmp_path, monkeypatch, capsys):
        root, deep = self._tree(tmp_path, "tools", "cc", "hooks")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "")
        monkeypatch.chdir(deep)
        assert _three_roots() == [root.resolve()] * 3
        assert "CLAUDE_PROJECT_DIR is empty" in capsys.readouterr().err

    def test_the_reflect_candidate_pass_walks_up_with_them(self, tmp_path, monkeypatch):
        root, deep = self._tree(tmp_path, "tools", "cc", "hooks")
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(deep)
        spec = importlib.util.spec_from_file_location("_reflect_root_rows", TOOLS_CC / "reflect_protocol.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module._candidate_root() == root.resolve()


class TestAKeptOlderPaths:
    def test_without_the_shared_resolver_the_hooks_keep_todays_rule(self, tmp_path, monkeypatch, translating):
        """A kept ``_paths.py`` that predates the resolver must degrade, never
        take the hooks down: the guarded import leaves today's rule, the
        translation included (no identity fallback, which would fail open on
        a deny compare)."""
        hu = _hook_utils()
        monkeypatch.setattr(hu, "_shared_root_spelling", None)
        drive = tmp_path / "drive"
        (drive / "repo").mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/c/repo")
        translating(_onto(drive))
        assert hu.resolve_project_root() == (drive / "repo").resolve()
        monkeypatch.delenv("CLAUDE_PROJECT_DIR")
        monkeypatch.chdir(tmp_path)
        assert hu._project_root_spelling() == "."


class TestNoFourthReader:
    """The variable has two readers: the resolver, and the hooks' degrade for
    a kept older ``_paths.py``. A third, read raw, is how three spellings came
    to disagree (the failure-mode review, 2026-11-08)."""

    _READERS = {("_paths.py", "project_root_spelling"), ("_hook_utils.py", "_project_root_spelling")}

    @staticmethod
    def _reads(tree) -> set[str]:
        """The innermost function (or ``<module>``) holding each read of the
        variable from the environment: ``os.environ.get``, ``os.getenv`` or a
        loaded ``os.environ[...]``. A write into a child's env is no read."""
        import ast

        def is_key(node) -> bool:
            return isinstance(node, ast.Constant) and node.value == "CLAUDE_PROJECT_DIR"

        def is_read(node) -> bool:
            if isinstance(node, ast.Call) and node.args and is_key(node.args[0]):
                callee = node.func
                name = getattr(callee, "attr", None) or getattr(callee, "id", None)
                owner = getattr(callee, "value", None)
                owner_name = getattr(owner, "attr", None) or getattr(owner, "id", None)
                return (name == "get" and owner_name == "environ") or name == "getenv"
            return (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load)
                    and is_key(node.slice) and getattr(node.value, "attr", None) == "environ")

        found: set[str] = set()

        def visit(node, scope: str) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scope = node.name
            if is_read(node):
                found.add(scope)
            for child in ast.iter_child_nodes(node):
                visit(child, scope)

        visit(tree, "<module>")
        return found

    def test_only_the_resolver_and_the_degrade_read_the_variable(self):
        import ast
        from tests._live_tree import checkout_rglob
        readers = {
            (path.name, fn)
            for path in sorted(checkout_rglob(TOOLS_CC, "*.py"))
            for fn in self._reads(ast.parse(path.read_text(encoding="utf-8")))
        }
        assert readers == self._READERS, (
            f"CLAUDE_PROJECT_DIR is read by {sorted(readers - self._READERS)} "
            f"(and no longer by {sorted(self._READERS - readers)}): call _paths._repo_root() "
            "(or _hook_utils.resolve_project_root() in a hook) instead"
        )

    def test_the_hooks_pass_the_translator_by_the_name_the_resolver_takes(self):
        """`_project_root_spelling` calls the shared resolver with
        ``translate=``, unguarded: a rename on one side only would raise in
        every deny hook (the failure-mode review's third note)."""
        import inspect
        assert "translate" in inspect.signature(_paths.project_root_spelling).parameters
        assert "translate=_msys_drive_to_windows" in inspect.getsource(_hook_utils()._project_root_spelling)


class TestARealKeptOlderPaths:
    @pytest.mark.parametrize("kept", ["without_the_resolver", "raising_at_import"])
    def test_the_guarded_import_itself_keeps_the_hooks_starting(self, tmp_path, monkeypatch, kept):
        """The module-level guard, not a patched attribute: ``_hook_utils``
        loaded (under an alias) beside a ``_paths`` that predates the resolver,
        or one whose import fails, starts and resolves by today's rule."""
        import types
        if kept == "without_the_resolver":
            older = types.ModuleType("_paths")
            older._repo_root = lambda: tmp_path  # type: ignore[attr-defined]
            monkeypatch.setitem(sys.modules, "_paths", older)
        else:
            monkeypatch.setitem(sys.modules, "_paths", None)   # the import raises ImportError
        spec = importlib.util.spec_from_file_location("_hook_utils_kept_older", HOOKS_DIR / "_hook_utils.py")
        assert spec is not None and spec.loader is not None
        hu = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(HOOKS_DIR))
        try:
            spec.loader.exec_module(hu)
        finally:
            sys.path.remove(str(HOOKS_DIR))
        assert hu._shared_root_spelling is None
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        assert hu._project_root_spelling() == str(tmp_path)


class TestTheWiringCanary:
    def test_a_git_bash_session_directory_goes_through_the_translation(
            self, tmp_path, monkeypatch, translating):
        spec = importlib.util.spec_from_file_location(
            "_canary_root_rows", REPO_ROOT / "scripts" / "hook_wiring_canary.py")
        assert spec is not None and spec.loader is not None
        canary = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(canary)
        drive = tmp_path / "drive"
        (drive / "repo").mkdir(parents=True)
        translating(_onto(drive))
        assert canary._session_dir("{}", {"CLAUDE_PROJECT_DIR": "/c/repo"}) == drive / "repo"
        translating(_identity)
        assert canary._session_dir("{}", {"CLAUDE_PROJECT_DIR": "/c/repo"}) == Path("/c/repo")
