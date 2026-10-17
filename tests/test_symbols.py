"""`tools/cc/_symbols.py`: the symbols a change touches, derived from its diff
(`TP-702` Wave 1). The mapper moved here from `scripts/lane_overlap_census.py`
with its cases: both sides of every hunk are placed, a decorator or a comment
block above a definition is the definition's, a blank line is neutral, a line no
node holds is UNPLACED and never a certificate, a file that is not Python is a
path tier. Added with the move: a lane read against the merge-base of its base
and its head, its working tree and untracked files included, so a base that
moved after the branch point reports none of the base's symbols as the lane's;
and the one mirror pair the deployed tools fold, pinned against the registry.
The mapper cases are in-process (the diffs come from `difflib`, which writes the
same `@@ -a,b +c,d @@` headers git does under `-U0`); the lane cases drive real
git in a scratch repository. The file pins the reading because a claim, the
plan pre-flight and the census all trust it: a line it misplaces is an overlap
no seat is told about. Each test names, in its docstring, the mutation it dies
to."""
# slow-exempt: about twenty twin rows of a few git calls each (a diff per side, merge-file, a three-commit merge-ort in a bare scratch repo) and the scratch-repository lane cases, beside in-process ones, measured 2026-10-17: 70 tests in 5.3 s on the Air
from __future__ import annotations

import difflib
import hashlib
import importlib.util
import pathlib
import re
import subprocess
import sys

import pytest

from tests._git_oracle import _git_env
from tests._quiet_git import NO_BACKGROUND_GIT
from tests._stubs import write_stub

_REPO = pathlib.Path(__file__).resolve().parents[1]
_MODULE = _REPO / "tools" / "cc" / "_symbols.py"


@pytest.fixture(scope="module")
def sym():
    spec = importlib.util.spec_from_file_location("_symbols_under_test", _MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["_symbols_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _lines(text: str) -> list[str]:
    """``text`` cut after each newline only, as git cuts it (``splitlines`` also cuts at a form
    feed and U+2028, which would give the diff the very skew a test here is about)."""
    return [piece for piece in re.split(r"(?<=\n)", text) if piece]


def _diff(old: str, new: str, path: str) -> str:
    return "".join(difflib.unified_diff(_lines(old), _lines(new), fromfile="a/" + path, tofile="b/" + path, n=0))


def _symbols(sym, old: str, new: str, path: str = "p.py") -> set[str]:
    return sym.changed_symbols(path, old, new, _diff(old, new, path))["symbols"]


def _placement(sym, old: str, new: str, path: str = "p.py") -> dict:
    return sym.changed_symbols(path, old, new, _diff(old, new, path))


def _named(symbols: set[str]) -> set[str]:
    """The symbols without the marks for what a hunk borders (a file's ``<start>`` and
    ``<end>``, a run of blanks ``<after:X>``): for a row about which symbol a change lands on."""
    return {s for s in symbols if not s.endswith(("::<start>", "::<end>")) and "::<after:" not in s}


OLD = '''import os

LIMIT = 3
TABLE = {
    "a": 1,
}
first, second = 1, 2


def f(x):
    return x + 1


def g(y):
    return y - 1


# the class
@decorate(1)
class C:
    attr = 0

    def m(self):
        return 1

    async def n(self):
        return 2


if TYPE_CHECKING:
    def h():
        return 3
'''


class TestChangedSymbols:
    def test_a_changed_line_lands_on_its_function(self, sym):
        """Dies to: the enclosing span read as the module for every line."""
        assert _symbols(sym, OLD, OLD.replace("return x + 1", "return x + 2")) == {"p.py::f"}

    def test_a_method_is_qualified_by_its_class(self, sym):
        """Dies to: the qualname prefix dropped (a bare `m`)."""
        assert _symbols(sym, OLD, OLD.replace("return 1", "return 10")) == {"p.py::C.m"}

    def test_an_async_def_is_a_symbol(self, sym):
        """Dies to: `ast.AsyncFunctionDef` left out of the walk (the line falls to `C`)."""
        assert _symbols(sym, OLD, OLD.replace("return 2", "return 20")) == {"p.py::C.n"}

    def test_a_top_level_assignment_is_its_target_name(self, sym):
        """Dies to: module-level assignments not walked (the line reads unplaced)."""
        assert _symbols(sym, OLD, OLD.replace('"a": 1,', '"a": 1,\n    "b": 2,')) == {"p.py::TABLE"}

    def test_a_tuple_target_binds_each_name(self, sym):
        """Dies to: the target spelled whole (`p.py::(first, second)`, a comma a step field splits on).
        TABLE is the line above the edit, its closing brace, which git conflicts with."""
        got = _symbols(sym, OLD, OLD.replace("first, second = 1, 2", "first, second = 3, 4"))
        assert got == {"p.py::first", "p.py::second", "p.py::TABLE"}, got
        assert not any("," in s for s in got), got

    def test_a_class_body_assignment_is_the_class_s(self, sym):
        """Dies to: class-body assignments made symbols of their own (`p.py::attr`)."""
        assert _symbols(sym, OLD, OLD.replace("attr = 0", "attr = 1")) == {"p.py::C"}

    def test_a_pure_deletion_is_placed_in_the_old_file(self, sym):
        """Dies to: deletions placed in the new file (they land on `f` or the module there)."""
        new = OLD.replace("def g(y):\n    return y - 1\n\n\n", "")
        got = _symbols(sym, OLD, new)
        # difflib slides the hunk up to f's last line, which it then borders: f is that neighbour.
        assert "p.py::g" in got and "p.py::C" not in got, got

    def test_the_git_shaped_hunk_for_a_whole_deletion_counts_only_the_deleted_def(self, sym):
        """Git slides the hunk for "delete `g` whole" to the def, its body and the two blanks
        below it (`@@ -14,4 +13,0 @@`), where difflib slides it two lines up. Dies to: blank lines
        attached to the next definition (the decorated class), which counted `C`'s lines beside
        `g`'s. `C` is named all the same, as the line below the hunk (its comment), which git
        conflicts with; its lines are not counted as changed."""
        new = OLD.replace("def g(y):\n    return y - 1\n\n\n", "")
        line_of_g = OLD.splitlines().index("def g(y):") + 1
        hunk = f"@@ -{line_of_g},4 +{line_of_g - 1},0 @@\n"
        got = sym.changed_symbols("p.py", OLD, new, hunk)
        # The two blanks it deletes are the run after g: the mark for that point.
        assert got["symbols"] == {"p.py::g", "p.py::C", "p.py::<after:g>"} and got["changed"] == 2, got
        assert got["unplaced"] == 0, got

    def test_a_method_added_at_the_end_of_a_class_names_only_that_method(self, sym):
        """Dies to: the blank line before the new method attached to the next top-level def. The
        insertion sits in the run of blanks below the class, and names that point: two lanes
        appending there conflict in git, and meet at it."""
        new = OLD.replace("        return 2\n", "        return 2\n\n    def o(self):\n        return 4\n")
        got = _placement(sym, OLD, new)
        assert got["symbols"] == {"p.py::C.o", "p.py::<after:C.n>"} and got["beside"] == 0, got

    def test_a_trailing_comment_after_a_body_is_unplaced_not_the_next_def(self, sym):
        """Dies to: a comment run that a blank line breaks still walking forward to the next def."""
        new = OLD.replace("    return x + 1\n", "    return x + 1\n# tail\n")
        got = _placement(sym, OLD, new)
        # f is the line the insertion follows, and the run of blanks after f the line below it;
        # g, past those blanks, is not touched.
        assert got["symbols"] == {"p.py::<module>", "p.py::f", "p.py::<after:f>"} and got["unplaced"] == 1, got

    def test_a_blank_line_between_methods_names_nothing(self, sym):
        """Dies to: a blank inside a class span producing the class (the two-rules finding)."""
        new = OLD.replace("        return 1\n\n    async def n", "        return 1\n\n\n    async def n")
        got = _placement(sym, OLD, new)
        # The blank names no definition and is not counted; `n`, the line it sits above, is its
        # neighbour, and the run of blanks after `m` the point it lands in.
        assert "p.py::C" not in got["symbols"] and got["changed"] == 0, got
        assert got["symbols"] == {"p.py::C.n", "p.py::<after:C.m>"}, got

    def test_a_rename_reports_both_names(self, sym):
        """Dies to: only the new side of a changed hunk placed (`f` vanishes, the other lane meets nothing)."""
        assert _symbols(sym, OLD, OLD.replace("def f(x):", "def f2(x):")) == {"p.py::f", "p.py::f2"}

    def test_one_hunk_that_deletes_g_and_extends_f_reports_both(self, sym):
        """Dies to: the old side of a changed hunk dropped (`g`'s deletion vanishes)."""
        new = OLD.replace("    return x + 1\n\n\ndef g(y):\n    return y - 1\n", "    return x + 1\n    return x\n")
        got = _symbols(sym, OLD, new)
        assert {"p.py::f", "p.py::g"} <= got, got

    def test_a_decorator_edit_is_the_definition_s(self, sym):
        """Dies to: a span starting at the `def`/`class` line, not its first decorator."""
        assert _symbols(sym, OLD, OLD.replace("@decorate(1)", "@decorate(2)")) == {"p.py::C"}

    def test_a_comment_block_above_a_definition_is_the_definition_s(self, sym):
        """Dies to: a comment outside every node left unplaced instead of attached to the next node."""
        assert _symbols(sym, OLD, OLD.replace("# the class", "# the class, renamed")) == {"p.py::C"}

    def test_a_definition_under_a_module_level_block_is_found(self, sym):
        """Dies to: the walk stopping at `if`/`try` blocks (the line reads unplaced)."""
        assert _named(_symbols(sym, OLD, OLD.replace("return 3", "return 30"))) == {"p.py::h"}

    def test_an_added_import_is_unplaced_and_counted(self, sym):
        """Dies to: unplaced lines dropped from the symbols, or not counted."""
        got = _placement(sym, OLD, OLD.replace("import os\n", "import os\nimport sys\n"))
        # The line it follows, `import os`, names nothing; the blank line below it is the run of
        # blanks the insertion lands in, the point it names.
        assert got["symbols"] == {"p.py::<module>", "p.py::<after:<module>>"}, got
        assert got["unplaced"] == 1 and got["changed"] == 1 and got["beside"] == 0, got

    def test_a_file_that_is_not_python_is_a_path_tier(self, sym):
        """Dies to: a prose file mapped as if it were Python (symbols by line)."""
        got = _placement(sym, "a\n", "b\n", "docs/x.md")
        assert got == {"kind": "path", "symbols": {"docs/x.md"}, "changed": 0, "unplaced": 0, "beside": 0}

    def test_unparseable_new_source_places_the_old_side_and_counts_the_new_as_unplaced(self, sym):
        """Dies to: a SyntaxError on one side emptying both sides' placement."""
        new = OLD.replace("def f(x):", "def f(x")     # a lane mid-edit
        got = _placement(sym, OLD, new)
        assert "p.py::f" in got["symbols"] and got["unplaced"] >= 1, got

    def test_a_null_byte_in_the_source_maps_nothing_and_raises_nothing(self, sym):
        """Python 3.10's parser raises ValueError, not SyntaxError, on a NUL byte (code review,
        driven). Dies to: only SyntaxError caught (a traceback out of `send --symbols-from`, and
        a plan pre-flight that drops every claim warning)."""
        assert sym.spans("def f():\n    return '\x00'\n") == []
        got = _placement(sym, OLD, OLD.replace("return x + 1", "return '\x00'"))
        assert got["unplaced"] >= 1, got

    def test_a_diff_with_no_hunk_it_can_read_is_unplaced_never_empty(self, sym):
        """A diff producer the user configured (an external differ, a colour code before every
        header) left no `@@` line to read, and an edited file read as nothing changed: the shape
        a pair verdict certifies as "different functions" (code review, driven). Dies to: a
        Python file with diff text and no parsed hunk read as zero changed, zero unplaced."""
        got = sym.changed_symbols("p.py", OLD, OLD.replace("x + 1", "x + 2"), "\x1b[1mdiff --git a/p.py\x1b[m\nsomething\n")
        assert got["symbols"] == {"p.py::<module>"} and got["unplaced"] == 1, got
        mode_only = "diff --git a/p.py b/p.py\nold mode 100644\nnew mode 100755\n"
        assert sym.changed_symbols("p.py", OLD, OLD, mode_only)["unplaced"] == 0


class TestSpans:
    def test_nested_definitions_are_qualified_and_the_innermost_wins(self, sym):
        """Dies to: the outermost span winning (a method's line reads as its class)."""
        nodes = sym.spans(OLD)
        names = {n for n, *_ in nodes}
        assert {"LIMIT", "TABLE", "first", "second", "f", "g", "C", "C.m", "C.n", "h"} <= names
        assert "attr" not in names
        line_of_m = OLD.splitlines().index("        return 1") + 1
        assert sym.enclosing(nodes, line_of_m) == "C.m"

    def test_every_diff_turns_rename_detection_off(self, sym):
        """Dies to: `--no-renames` dropped (a moved file reads as added at the new path only)."""
        assert "--no-renames" in sym.DIFF_ARGS

    def test_every_diff_reads_plain_text(self, sym):
        """Dies to: a colour, external-diff or textconv setting in the box's git config turning the
        hunk header into something `HUNK_RE` does not match, so nothing is read and all is certified."""
        assert {"--no-color", "--no-ext-diff", "--no-textconv", "--inter-hunk-context=0",
                "--no-indent-heuristic", "--diff-algorithm=histogram"} <= set(sym.DIFF_ARGS)


class TestNothingReadIsNeverCertified:
    def test_a_file_with_no_counted_lines_is_unplaced_not_certified(self, sym):
        """Dies to: a side with zero counted lines certified (a diff the mapper never read: an
        empty diff from a subdirectory run, a hunk header a colour config broke, a side git could
        not read, a blank-only edit) printed as different functions, where git conflicts."""
        nothing = {"p.py": {"kind": "python", "symbols": set(), "changed": 0, "unplaced": 0}}
        some = {"p.py": {"kind": "python", "symbols": {"p.py::f"}, "changed": 1, "unplaced": 0}}
        assert sym.pair_verdict(nothing, some)["verdict"] == "unplaced"
        assert sym.pair_verdict(some, nothing)["verdict"] == "unplaced"
        assert sym.pair_verdict(nothing, nothing)["verdict"] == "unplaced"

    def test_a_line_the_source_does_not_have_is_unplaced_and_counted(self, sym):
        """Dies to: a line past the end of a side (a side git could not read) read as a blank, so
        it counts for nothing and the file is certified."""
        got = sym.changed_symbols("p.py", "", "", "@@ -0,0 +1,3 @@\n")
        assert got["changed"] == 3 and got["unplaced"] == 3, got

    def test_a_form_feed_line_does_not_shift_the_line_index(self, sym):
        """Dies to: `str.splitlines()`, which also splits on form feed, U+2028 and friends where
        git and `ast` split on newlines only, so every line after one is read one off."""
        old, new = "\x0c\nimport os\n", "\x0c\nimport sys\n"
        got = sym.changed_symbols("p.py", old, new, "@@ -2 +2 @@\n")
        assert got["changed"] == 2 and got["unplaced"] == 2, got


class TestPlacementEdges:
    def test_a_blank_line_inside_a_function_is_the_function_s(self, sym):
        """Dies to: every blank line neutral, where git conflicts on the edit beside this one."""
        old = "def f(x):\n    y = x\n    return y\n\n\ndef g():\n    return 2\n"
        new = old.replace("    y = x\n", "    y = x\n\n")
        got = _placement(sym, old, new)
        assert got["symbols"] == {"p.py::f"} and got["changed"] == 1 and got["unplaced"] == 0, got

    def test_a_blank_line_between_top_level_definitions_stays_neutral(self, sym):
        """Dies to: a blank line outside every node handed to a neighbour."""
        old = "def f(x):\n    return x\n\n\ndef g():\n    return 2\n"
        new = old.replace("\n\n\ndef g", "\n\n\n\ndef g")
        got = _placement(sym, old, new)
        # The blank is not counted (changed stays 0); `g`, the line it sits above, is its
        # neighbour, and the run of blanks after `f` the point it lands in.
        assert got["symbols"] == {"p.py::g", "p.py::<after:f>"} and got["changed"] == 0, got

    def test_an_indented_trailing_comment_is_unplaced_not_the_next_def(self, sym):
        """Dies to: the forward walk ignoring indentation, so a comment indented as `f`'s body with
        no blank before `def g` is handed to `g` (git conflicts with an edit on `f`'s last line)."""
        old = "def f():\n    return 1\n    # done\ndef g():\n    return 2\n"
        new = old.replace("# done", "# finished")
        got = _placement(sym, old, new)
        # g is named all the same, as the line below the edit with no blank between (git
        # conflicts with an edit there); the comment's own two lines stay unplaced.
        assert got["unplaced"] == 2 and got["symbols"] == {"p.py::<module>", "p.py::f", "p.py::g"}, got

    def test_a_subscript_target_is_its_root_name(self, sym):
        """Dies to: `ast.unparse` of a subscript target (`X[1, 2]`), which carries the comma the
        tuple-target test exists to keep out of a symbol."""
        old = "X = {}\nX[1, 2] = 3\n"
        assert _named(_symbols(sym, old, old.replace("= 3", "= 4"))) == {"p.py::X"}


class TestPairVerdict:
    @staticmethod
    def _py(symbols, unplaced=0):
        return {"kind": "python", "symbols": set(symbols), "changed": len(symbols) + unplaced, "unplaced": unplaced}

    def test_a_shared_symbol_is_the_verdict(self, sym):
        """Dies to: the shared set computed over one side only."""
        got = sym.pair_verdict({"p.py": self._py({"p.py::f"})}, {"p.py": self._py({"p.py::f", "p.py::g"})})
        assert got["verdict"] == "shared symbol" and got["shared"] == ["p.py::f"]

    def test_different_functions_needs_every_line_placed_on_both_sides(self, sym):
        """Dies to: unplaced lines dropped before the verdict, the review's finding: a certificate
        printed exactly where the mapper knows nothing."""
        certified = sym.pair_verdict({"p.py": self._py({"p.py::f"})}, {"p.py": self._py({"p.py::g"})})
        assert certified["verdict"] == "different functions" and certified["certified"] == ["p.py"]
        blind = sym.pair_verdict({"p.py": self._py({"p.py::f", "p.py::<module>"}, unplaced=1)},
                                 {"p.py": self._py({"p.py::g", "p.py::<module>"}, unplaced=1)})
        assert blind["verdict"] == "unplaced" and blind["certified"] == [], blind

    def test_a_class_on_one_side_meets_its_method_on_the_other(self, sym):
        """The one rule the claims matcher and the verdict both use. Dies to: the verdict
        comparing names for equality only (the plan warns while the board certifies)."""
        got = sym.pair_verdict({"p.py": self._py({"p.py::C"})}, {"p.py": self._py({"p.py::C.n"})})
        assert got["verdict"] == "shared symbol" and got["shared"] == ["p.py::C"], got
        assert sym.symbols_meet({"p.py::C"}, {"p.py::C.n"}) == {"p.py::C"}
        assert sym.symbols_meet({"p.py::Cx"}, {"p.py::C.n"}) == set()

    def test_a_shared_module_line_is_never_a_shared_symbol(self, sym):
        """Dies to: `<module>` admitted to the shared set."""
        got = sym.pair_verdict({"p.py": self._py({"p.py::<module>"}, 1)}, {"p.py": self._py({"p.py::<module>"}, 1)})
        assert got["verdict"] == "unplaced" and got["shared"] == []

    def test_prose_files_are_a_path_tier_not_a_symbol(self, sym):
        """Dies to: a non-Python file counted as a shared symbol."""
        prose = {"kind": "path", "symbols": {"docs/x.md"}, "changed": 0, "unplaced": 0}
        got = sym.pair_verdict({"docs/x.md": prose}, {"docs/x.md": dict(prose)})
        assert got["verdict"] == "path only" and got["paths"] == ["docs/x.md"] and got["shared"] == []

    def test_no_shared_file_is_no_verdict(self, sym):
        got = sym.pair_verdict({"a.py": self._py({"a.py::f"})}, {"b.py": self._py({"b.py::f"})})
        assert got["verdict"] == "none" and got["files"] == []

    def test_the_verdicts_named_are_the_ones_pair_verdict_gives(self, sym):
        """Derived, not restated: every string `pair_verdict` assigns to `verdict` is in
        `VERDICTS` and the other way round. Dies to: a new verdict added to the function and not
        to the constant (the board would sort it past the cap and word it as prose, the census
        would leave it out of its counts)."""
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(sym.pair_verdict))
        given = {node.value.value for node in ast.walk(tree)
                 if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "verdict" for t in node.targets)
                 and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)}
        assert given and given == set(sym.VERDICTS), (given, sym.VERDICTS)


#: Two functions, two blank lines between, and no blank line at the end.
_TWO = "def f():\n    return 1\n\n\ndef g():\n    return 2\n"


def _merge_file_rc(tmp_path: pathlib.Path, base: str, ours: str, theirs: str) -> int:
    """``git merge-file``'s exit code (0 clean, else the number of conflicts): a stand-in, which
    diffs each side with git's default algorithm."""
    files = []
    for name, text in (("ours", ours), ("base", base), ("theirs", theirs)):
        path = tmp_path / f"{name}.py"
        path.write_bytes(text.encode("utf-8"))
        files.append(str(path))
    return subprocess.run(["git", "merge-file", "-p", *files], capture_output=True, timeout=30).returncode


_WHO = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_AUTHOR_DATE": "1000000000 +0000",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_DATE": "1000000000 +0000"}


def _ort_rc(tmp_path: pathlib.Path, base: str, ours: str, theirs: str) -> int:
    """merge-ort's exit code (``git merge-tree --write-tree``: 0 clean, 1 conflicted), the merge
    the ship driver's catch-up and the host run, in a bare scratch repository of three commits.
    It needs git 2.38: older, the row is skipped, never read as clean. The box's own config and
    attributes are kept out (a ``merge=union`` there merges every conflict clean; the code
    review of Wave 2's last delta, driven)."""
    version = re.search(r"(\d+)\.(\d+)", subprocess.run(["git", "--version"], capture_output=True, text=True,
                                                         encoding="utf-8", timeout=30).stdout)
    if not version or (int(version.group(1)), int(version.group(2))) < (2, 38):
        pytest.skip("git merge-tree --write-tree needs git 2.38 or later")
    repo = tmp_path / f"ort{len(list(tmp_path.glob('ort*')))}"
    repo.mkdir()
    (repo / "empty.gitconfig").write_bytes(b"")
    # git's config also arrives through the environment (`GIT_CONFIG_COUNT` and its pairs, and the
    # `GIT_CONFIG_PARAMETERS` a parent `git -c` exports): none of it reaches the oracle either.
    env = {**{k: v for k, v in _git_env().items() if not k.startswith("GIT_CONFIG")}, **_WHO, "HOME": str(repo),
           "XDG_CONFIG_HOME": str(repo), "GIT_CONFIG_NOSYSTEM": "1", "GIT_ATTR_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": str(repo / "empty.gitconfig")}

    def git(*args: str, data: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, env=env, timeout=30,
                              input=None if data is None else data.encode("utf-8"))

    git("init", "-q", "--bare")
    for key, value in NO_BACKGROUND_GIT:
        git("config", key, value)

    def commit(text: str, *parents: str) -> str:
        blob = git("hash-object", "-w", "--stdin", data=text).stdout.decode().strip()
        tree = git("mktree", data=f"100644 blob {blob}\tp.py\n").stdout.decode().strip()
        return git("commit-tree", tree, "-m", "c", *(a for p in parents for a in ("-p", p))).stdout.decode().strip()

    first = commit(base)
    result = git("merge-tree", "--write-tree", commit(ours, first), commit(theirs, first))
    assert result.returncode in (0, 1) and result.stdout.strip(), result.stderr
    return result.returncode


def _merge_rc(tmp_path: pathlib.Path, base: str, ours: str, theirs: str) -> int:
    """git's own answer from both its mergers: 0 only where merge-file and merge-ort both merge
    clean, else the conflicts either finds. A row that pins a conflict holds where either
    conflicts, and a clean control only where both are clean (the failure-mode review of Wave 2's
    last delta, driven: merge-file alone, diffing as git's default does, merged a pair merge-ort
    conflicts on, and the row read clean)."""
    return max(_merge_file_rc(tmp_path, base, ours, theirs), _ort_rc(tmp_path, base, ours, theirs))


#: A test class with a method, then two blank lines, then another class: the commonest co-edit.
_CLS = ("class TestA:\n    def test_one(self):\n        assert 1\n\n\n"
        "class TestB:\n    def test_two(self):\n        assert 2\n")
#: Documented constants one blank line apart, this repository's own idiom.
_DOC = "def f():\n    return 1\n\n\n#: doc\nLIMIT = 3\n\n\ndef g():\n    return 2\n"


def _git_placement(sym, tmp_path: pathlib.Path, old: str, new: str) -> dict:
    """One side's placement from git's own diff (``git diff --no-index -U0`` with the mapper's
    ``DIFF_ARGS``), the differ production reads: where a hunk sits is what the neighbour rule
    reads, and difflib sits some insertions elsewhere."""
    where = tmp_path / f"side{len(list(tmp_path.glob('side*')))}"
    where.mkdir()
    (where / "old.py").write_bytes(old.encode("utf-8"))
    (where / "new.py").write_bytes(new.encode("utf-8"))
    diff = subprocess.run(["git", "diff", "--no-index", "-U0", *sym.DIFF_ARGS, "old.py", "new.py"],
                          cwd=where, capture_output=True, text=True, encoding="utf-8", timeout=30).stdout
    return sym.changed_symbols("p.py", old, new, diff)


class TestTouchingHunksAreNeverCertified:
    """Two changes git cannot merge (they touch, or both land at one point) must never read
    "different functions", and one git merges must still read it, but for a row that records a
    cost by name. Each row places both sides through git's own diff and pins the verdict beside
    the exit codes of both git mergers (``_merge_rc``), so the rule follows git and not a
    sentence (the failure-mode reviews of Wave 2, driven: every conflicting shape here was
    certified before its fix)."""

    def _row(self, sym, tmp_path, ours: str, theirs: str, base: str = _TWO) -> tuple[str, int]:
        verdict = sym.pair_verdict({"p.py": _git_placement(sym, tmp_path, base, ours)},
                                   {"p.py": _git_placement(sym, tmp_path, base, theirs)})["verdict"]
        return verdict, _merge_rc(tmp_path, base, ours, theirs)

    def test_two_appends_at_the_end_of_a_file_meet(self, sym, tmp_path):
        """Dies to: an insertion placed by its own lines alone (two new functions appended read
        as different functions; git conflicts, both land after the last line)."""
        verdict, rc = self._row(sym, tmp_path, _TWO + "\n\ndef h1():\n    return 3\n",
                                _TWO + "\n\ndef h2():\n    return 4\n")
        assert rc != 0 and verdict != "different functions", (verdict, rc)

    def test_two_appends_after_a_trailing_blank_meet_at_the_end(self, sym, tmp_path):
        """Dies to: a neighbour past the last line read as nothing (behind a trailing blank, the
        last line names no symbol, so only the end of the file says they meet)."""
        base = _TWO + "\n"
        a, b = base + "\ndef h1():\n    return 3\n", base + "\ndef h2():\n    return 4\n"
        got = sym.pair_verdict({"p.py": _git_placement(sym, tmp_path, base, a)},
                               {"p.py": _git_placement(sym, tmp_path, base, b)})
        assert _merge_rc(tmp_path, base, a, b) != 0 and got["verdict"] == "shared symbol", got
        assert "p.py::<end>" in got["shared"], got

    def test_an_edit_and_an_insertion_right_after_it_meet(self, sym, tmp_path):
        """Dies to: an edit's neighbours left unplaced (f's last line edited, a new function
        inserted right after it with no blank between; git conflicts, the hunks touch)."""
        verdict, rc = self._row(sym, tmp_path, _TWO.replace("return 1", "return 10"),
                                _TWO.replace("    return 1\n", "    return 1\ndef h():\n    return 3\n"))
        assert rc != 0 and verdict == "shared symbol", (verdict, rc)

    def test_two_methods_appended_to_a_class_above_another_never_certify(self, sym, tmp_path):
        """Dies to: an insertion between two blank lines read as placed (git sits both
        insertions in the blank gap below the class, so neither neighbour names anything; the
        code review of the delta, driven: certified while git conflicts)."""
        add = "        assert 1\n\n    def test_{0}(self):\n        assert 3\n"
        verdict, rc = self._row(sym, tmp_path, _CLS.replace("        assert 1\n", add.format("a")),
                                _CLS.replace("        assert 1\n", add.format("b")), base=_CLS)
        assert rc != 0 and verdict != "different functions", (verdict, rc)

    def test_two_lines_inserted_into_one_blank_gap_never_certify(self, sym, tmp_path):
        """Dies to: the same, for two statements set into the two blank lines between functions."""
        verdict, rc = self._row(sym, tmp_path, _TWO.replace("    return 1\n\n\n", "    return 1\n\nX = 1\n\n"),
                                _TWO.replace("    return 1\n\n\n", "    return 1\n\nY = 2\n\n"))
        assert rc != 0 and verdict != "different functions", (verdict, rc)

    def test_two_documented_constants_added_below_one_never_certify(self, sym, tmp_path):
        """Dies to: the same, in this repository's own idiom (a `#:` constant one blank line
        below another; the failure-mode review of the delta, driven)."""
        verdict, rc = self._row(sym, tmp_path, _DOC.replace("LIMIT = 3\n", "LIMIT = 3\n\n#: a\nA = 1\n"),
                                _DOC.replace("LIMIT = 3\n", "LIMIT = 3\n\n#: b\nB = 2\n"), base=_DOC)
        assert rc != 0 and verdict != "different functions", (verdict, rc)

    def test_two_insertions_between_two_module_lines_never_certify(self, sym, tmp_path):
        """Dies to: an insertion that names no point read as placed (between two imports, its
        neighbours name nothing and its own lines name a new function each; git conflicts at
        the one point both land on)."""
        base = "import os\nimport sys\n\n\ndef f():\n    return 1\n"
        ours = base.replace("import os\n", "import os\ndef h():\n    return 2\n")
        verdict, rc = self._row(sym, tmp_path, ours,
                                base.replace("import os\n", "import os\ndef k():\n    return 3\n"), base=base)
        assert rc != 0 and verdict != "different functions", (verdict, rc)
        # The decline reaches a claim only through the mark the placement carries.
        got = _git_placement(sym, tmp_path, base, ours)
        assert got["beside"] == 1 and "p.py::<module>" in got["symbols"], got

    def test_a_pasted_copy_beside_another_lanes_edit_never_certifies(self, sym, tmp_path):
        """Dies to: git diff's indent heuristic left on (it slides the pasted copy to the top of
        its range, where it reads clear of the edit, while the merge places it at the bottom,
        beside the edit; the code review of Wave 2's last delta, driven)."""
        base = "X = 1\n\n\ndef f(x):\n    return x + 1\n\n\ndef g(y):\n    return y\n"
        pasted = base.replace("\n\n\ndef g", "\n\n\ndef f(x):\n    return x + 1\n\n\ndef g")
        verdict, rc = self._row(sym, tmp_path, pasted, base.replace("def g(y):", "def g(y=0):"), base=base)
        assert rc != 0 and verdict != "different functions", (verdict, rc)

    def test_a_run_of_blanks_at_the_top_of_a_file_is_its_start(self, sym, tmp_path):
        """Dies to: the walk up a run of blanks past the first line naming the module (two lanes
        inserting into the blank lines a file opens with meet at its start)."""
        base = "\n\ndef f():\n    return 1\n"
        got = _git_placement(sym, tmp_path, base, base.replace("\n\ndef f", "\nX = 1\n\ndef f", 1))
        assert "p.py::<start>" in got["symbols"], got

    def test_a_run_of_blanks_after_a_tuple_target_names_each_target(self, sym, tmp_path):
        """Dies to: the names a line binds joined with a comma (the comma a step field splits on)."""
        base = "a, b = 1, 2\n\n\ndef f():\n    return 1\n"
        got = _git_placement(sym, tmp_path, base, base.replace("a, b = 1, 2\n\n", "a, b = 1, 2\n\nY = 3\n"))
        assert "p.py::<after:a+b>" in got["symbols"], got

    def test_two_edits_either_side_of_an_import_stay_certified(self, sym, tmp_path):
        """The clean control for the line above. Dies to: an edit's neighbour that no node holds
        read as a decline (the untouched import between the two edits keeps them apart; git
        merges them)."""
        base = "def f(): return 1\nimport os\ndef g(): return 2\n"
        verdict, rc = self._row(sym, tmp_path, base.replace("return 1", "return 10"),
                                base.replace("return 2", "return 20"), base=base)
        assert rc == 0 and verdict == "different functions", (verdict, rc)

    def test_an_edit_and_an_insertion_two_lines_on_stay_certified(self, sym, tmp_path):
        """The clean control. Dies to: a rule wider than git's (an unchanged line between the
        two changes, which git merges, read as a meeting: a certificate lost for nothing)."""
        verdict, rc = self._row(sym, tmp_path, _TWO.replace("return 1", "return 10"),
                                _TWO.replace("\n\ndef g", "\n\ndef h():\n    return 3\n\n\ndef g"))
        assert rc == 0 and verdict == "different functions", (verdict, rc)

    def test_an_edit_at_the_first_line_keeps_its_certificate_elsewhere(self, sym, tmp_path):
        """Dies to: the start of the file read as unplaced (every edit to line 1 would decline,
        though git merges it with an edit far below)."""
        verdict, rc = self._row(sym, tmp_path, _TWO.replace("def f():", "def f(x=0):"),
                                _TWO.replace("return 2", "return 20"))
        assert rc == 0 and verdict == "different functions", (verdict, rc)

    def test_a_line_added_above_a_deleted_function_meets_a_deletion_beside_it(self, sym, tmp_path):
        """Dies to: git's default diff algorithm in the mapper's diff (it reads the new constant
        and the deletion as two replacements, the deleted function's blank lines untouched, clear
        of the other lane's deletion right below them), or a twin-row oracle of merge-file alone,
        which diffs that way too and merges the pair: merge-ort, which diffs by histogram,
        conflicts (the failure-mode review of Wave 2's last delta, driven end to end)."""
        base = "X = 1\n\n\ndef f0():\n    return x\n    pass\n\n\ndef f1():\n    x = 1\n    pass\n\n\ndef f2():\n    pass\n"
        ours = "Cc = 1\n\n" + base.replace("def f0():\n    return x\n    pass\n\n\n", "")
        theirs = base.replace("def f1():\n    x = 1\n    pass\n\n\n", "")
        verdict, rc = self._row(sym, tmp_path, ours, theirs, base=base)
        assert rc != 0 and verdict != "different functions", (verdict, rc)
        assert _merge_file_rc(tmp_path, base, ours, theirs) == 0   # the stand-in alone reads it clean

    def test_two_runs_after_module_level_lines_meet_though_git_merges_them(self, sym, tmp_path):
        """A recorded cost, not a guarantee: every run of blanks after a line that names nothing
        is one mark, ``<after:<module>>``, so two functions added under two section comments meet
        though git merges them (the failure-mode review of Wave 2's last delta, shape 33). The
        direction is conservative; keying the run by its own lines is the change that flips this
        row to a certificate (and, as any edit to the mapper is, a new ``_symbols.RULE``)."""
        base = "# one\n\n\ndef f():\n    return 1\n\n\n# two\n\n\ndef g():\n    return 2\n"
        ours = base.replace("# one\n\n", "# one\n\ndef h():\n    return 3\n\n")
        theirs = base.replace("# two\n\n", "# two\n\ndef k():\n    return 4\n\n")
        verdict, rc = self._row(sym, tmp_path, ours, theirs, base=base)
        assert rc == 0 and verdict == "shared symbol", (verdict, rc)


class TestMarkWords:
    """Every mark a placement emits is said in words by the one renderer the board, the stale
    clause and the census share, so a mark is worded once and never reaches a line raw."""

    BASE = "a, b = 1, 2\n\n\nclass C:\n    def m(self):\n        return 1\n\n\n# one\n\nX = 1\n"
    SHAPES = {
        "<start>": "Z = 0\n" + BASE,
        "<end>": BASE + "Y = 2\n",
        "<after:a+b>": BASE.replace("a, b = 1, 2\n\n", "a, b = 1, 2\n\nW = 3\n"),
        "<after:<module>>": BASE.replace("# one\n\n", "# one\n\nV = 4\n"),
    }

    def test_every_mark_a_placement_emits_is_said_in_words(self, sym, tmp_path):
        """Dies to: a mark kind the renderer does not know (a new or renamed mark falls back to
        its raw spelling on every reader's line). The marks are read from placements, not
        written here; ``<module>`` alone is left out, since no reader ever names it as met."""
        marks = set()
        for want, new in self.SHAPES.items():
            got = {s for s in _git_placement(sym, tmp_path, self.BASE, new)["symbols"]
                   if "::<" in s and not s.endswith(f"::{sym.MODULE}")}
            assert f"p.py::{want}" in got, (want, got)
            marks |= got
        for mark in sorted(marks):
            for words in (sym.mark_words(mark), sym.mark_words(mark, in_file=True)):
                assert "<" not in words and ">" not in words and "+" not in words, (mark, words)
            assert "p.py" not in sym.mark_words(mark, in_file=True), mark
            assert "p.py" in sym.mark_words(mark), mark

    def test_the_words_say_what_a_mark_does_not_tell_apart(self, sym):
        """Dies to: every run after a module-level line worded as one run (it is one mark for
        every such run, so a meeting there may be two runs git merges apart), or a line's two
        targets printed joined (the failure-mode review of Wave 2's last delta, driven)."""
        assert "which run is not told apart" in sym.mark_words("p.py::<after:<module>>")
        assert sym.mark_words("p.py::<after:a+b>") == "the blank lines after p.py::a and p.py::b"
        assert sym.mark_words("p.py::<after:a+b>", in_file=True) == "the blank lines after a and b"


class TestTheRuleIsTheSource:
    """``_symbols.RULE`` is a digest of the mapper's own source, so any edit to it is a new rule
    and a claim placed by other code reads whole. A hand-bumped number, its record and the corpus
    that pinned it were each got past in turn (the failure-mode reviews of Wave 2's fourth to
    sixth deltas, driven: a placement moved under the same number, an input kind no shape held,
    a record moved out of the check's reach, a claim sent from an edited working tree). It names
    these bytes only: not the interpreter (a digest of the parse splits seats by Python version),
    git's diff, or how mail.py shapes the list."""

    def _load(self, tmp_path: pathlib.Path, source: bytes, name: str):
        """The mapper from ``source``, loaded from a scratch copy; its sibling is the real one."""
        where = tmp_path / name
        where.mkdir()
        (where / "_symbols.py").write_bytes(source)
        spec = importlib.util.spec_from_file_location(f"_symbols_rule_{name}", where / "_symbols.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_any_edit_is_a_new_rule_and_line_endings_are_none(self, sym, tmp_path, monkeypatch):
        """Dies to: a rule kept by hand or read from anything but these bytes (an edit left at the
        old rule: a claim from the edited tree certifies against readers of the other; salted by
        the interpreter, it splits seats by Python version, and each CI cell computes its own, so
        nothing would notice), a digest blind to whitespace or to comments (one space, or one
        comment byte, left at the old rule), or a checkout's line endings read as an edit (a
        Windows seat and a Mac seat on one commit would read each other's claims whole)."""
        # Each copy puts its own folder first on the path at import: none outlives this row.
        monkeypatch.setattr(sys, "path", list(sys.path))
        monkeypatch.setattr(sys, "modules", dict(sys.modules))
        lf = _MODULE.read_bytes().replace(b"\r\n", b"\n")
        assert sym.RULE == hashlib.sha256(lf).hexdigest()[:16]
        assert self._load(tmp_path, lf.replace(b"\n", b"\r\n"), "crlf").RULE == sym.RULE
        comment = lf.replace(b"#: The edges of a file", b"#: the edges of a file", 1)
        space = lf.replace(b'MODULE = "<module>"\n', b'MODULE = "<module>" \n', 1)
        assert comment != lf and space != lf
        assert self._load(tmp_path, comment, "comment").RULE != sym.RULE
        assert self._load(tmp_path, space, "space").RULE != sym.RULE


class TestConcurrent:
    def test_two_windows_that_overlap_are_concurrent_and_disjoint_ones_are_not(self, sym):
        """Dies to: the window test inverted or one-sided."""
        a = {"created": "2026-10-16T10:00:00Z", "merged": "2026-10-16T12:00:00Z"}
        b = {"created": "2026-10-16T11:00:00Z", "merged": "2026-10-16T13:00:00Z"}
        c = {"created": "2026-10-16T12:30:00Z", "merged": "2026-10-16T14:00:00Z"}
        assert sym.concurrent(a, b) and sym.concurrent(b, a)
        assert not sym.concurrent(a, c) and not sym.concurrent(c, a)


class TestCanonical:
    def test_the_vendored_twin_folds_onto_its_source_and_the_pair_is_the_registry_s(self, sym):
        """The deployed tools own one mirror pair, and the module folds it with no engine
        import. Dies to: the pair spelled apart from `espalier/mirror_registry.py`'s `vendor-cc`
        row (a renamed vendor directory, and every lane meets another twice), or the fold dropped."""
        sys.path.insert(0, str(_REPO))
        try:
            from espalier import mirror_registry
        finally:
            sys.path.remove(str(_REPO))
        row = mirror_registry.row("vendor-cc")
        base = mirror_registry.glob_row_parts(row.sot)
        assert base is not None
        assert (sym.VENDOR_MIRROR, sym.VENDOR_SOURCE) == (row.mirrors[0], base[0])
        assert sym.canonical("espalier/_vendor/cc/hooks/write_guard.py") == "tools/cc/hooks/write_guard.py"
        assert sym.canonical("tools/cc/mail.py") == "tools/cc/mail.py"
        assert sym.canonical("docs/HOOKS.md") == "docs/HOOKS.md"


# ---------------------------------------------------------------- a lane, read by git

def _git(root: pathlib.Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
         *args], cwd=root, check=True, capture_output=True, text=True, encoding="utf-8", timeout=30,
    ).stdout


MOD = "def f():\n    return 1\n\n\ndef g():\n    return 2\n"


@pytest.fixture()
def repo(tmp_path):
    """A scratch repository on `main` with one module holding `f` and `g`, and a lane branch."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "m.py").write_text(MOD, encoding="utf-8")
    _git(root, "add", "m.py")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "switch", "-q", "-c", "lane")
    return root


class TestSymbolsOfLane:
    def test_a_clean_tree_reads_the_same_from_the_working_tree_and_from_head(self, sym, repo):
        """On a clean tree the lane's reading and the committed range's are one. Dies to: the
        two readers diverging in what they fold or count (a twin, a path tier, a blank)."""
        (repo / "m.py").write_text(MOD.replace("return 1", "return 10"), encoding="utf-8")
        _git(repo, "commit", "-q", "-am", "lane edits f")
        merge_base = _git(repo, "merge-base", "main", "HEAD").strip()
        lane = sym.symbols_of_lane(repo, "main")
        head = sym.symbols_between(merge_base, "HEAD", root=repo)
        assert lane == head
        assert lane["m.py"]["symbols"] == {"m.py::f"}

    def test_a_base_that_moved_after_the_branch_point_reports_the_lane_s_symbols_alone(self, sym, repo):
        """Dies to: the lane diffed against the base's tip instead of the merge-base (the
        base's own edit of `g` reported as the lane's)."""
        (repo / "m.py").write_text(MOD.replace("return 1", "return 10"), encoding="utf-8")
        _git(repo, "commit", "-q", "-am", "lane edits f")
        _git(repo, "switch", "-q", "main")
        (repo / "m.py").write_text(MOD.replace("return 2", "return 20"), encoding="utf-8")
        _git(repo, "commit", "-q", "-am", "the base edits g")
        _git(repo, "switch", "-q", "lane")
        assert sym.symbols_of_lane(repo, "main")["m.py"]["symbols"] == {"m.py::f"}

    def test_an_uncommitted_edit_and_an_untracked_file_are_the_lane_s(self, sym, repo):
        """Dies to: the diff read from HEAD instead of the working tree (the edit to `g` is
        missed), or the untracked files left out (`n.py` is missed)."""
        (repo / "m.py").write_text(MOD.replace("return 2", "return 20"), encoding="utf-8")
        (repo / "n.py").write_text("def k():\n    return 3\n", encoding="utf-8")
        got = sym.symbols_of_lane(repo, "main")
        assert _named(got["m.py"]["symbols"]) == {"m.py::g"}
        assert _named(got["n.py"]["symbols"]) == {"n.py::k"} and got["n.py"]["unplaced"] == 0

    def test_an_uncommitted_edit_is_placed_in_the_working_tree_s_lines(self, sym, repo):
        """The working tree adds lines above the edited function, so HEAD's text places the
        changed line on the wrong definition (code review: the edit above changed a line
        without shifting any, and a reader of HEAD's text passed it). Dies to: the new side's
        source read from HEAD instead of the working tree."""
        grown = "def e():\n    return 0\n\n\n" + MOD.replace("return 2", "return 20")
        (repo / "m.py").write_text(grown, encoding="utf-8")
        got = sym.symbols_of_lane(repo, "main")["m.py"]
        # f is named too, as the first line the insertion at the top sits above.
        assert {"m.py::e", "m.py::g"} <= got["symbols"] and got["unplaced"] == 0, got

    def test_the_user_s_diff_settings_do_not_change_the_reading(self, sym, repo):
        """A colour forced on, and hunks merged across a context gap, are the user's git
        config and not the lane: with `color.diff=always` no `@@` parsed and the edit read as
        nothing; with `diff.interHunkContext` an untouched function between two edited ones
        was reported (code review, driven). Dies to: the diff flags that pin the format
        dropped from `DIFF_ARGS`."""
        three = "def a():\n    return 1\n\n\ndef b():\n    return 2\n\n\ndef c():\n    return 3\n"
        (repo / "m.py").write_text(three, encoding="utf-8")
        _git(repo, "commit", "-q", "-am", "three")
        _git(repo, "switch", "-q", "main")
        _git(repo, "merge", "-q", "--ff-only", "lane")
        _git(repo, "switch", "-q", "lane")
        (repo / "m.py").write_text(three.replace("return 1", "return 10").replace("return 3", "return 30"),
                                   encoding="utf-8")
        _git(repo, "config", "color.diff", "always")
        _git(repo, "config", "diff.interHunkContext", "10")
        got = sym.symbols_of_lane(repo, "main")["m.py"]
        assert _named(got["symbols"]) == {"m.py::a", "m.py::c"} and got["changed"] == 4, got

    @pytest.mark.skipif(sys.platform == "win32", reason="a POSIX shell script as the external differ")
    def test_an_external_differ_the_user_set_is_not_the_reading(self, sym, repo, tmp_path):
        """`diff.external` (a difftool's documented setup) replaced git's own diff text with
        whatever that program prints, and the edit read as nothing changed (code review,
        driven). Dies to: `--no-ext-diff` dropped from `DIFF_ARGS`."""
        silent = write_stub(tmp_path / "silent-differ.sh", "#!/bin/sh\nexit 0\n")
        _git(repo, "config", "diff.external", str(silent))
        (repo / "m.py").write_text(MOD.replace("return 1", "return 10"), encoding="utf-8")
        assert sym.symbols_of_lane(repo, "main")["m.py"]["symbols"] == {"m.py::f"}

    def test_an_ignored_file_is_not_the_lane_s(self, sym, repo):
        """Dies to: `--exclude-standard` dropped from the untracked listing (a claim takes a
        virtualenv, a dotenv file and the local settings, and parses thousands of files a tick)."""
        (repo / ".gitignore").write_text("build/\n", encoding="utf-8")
        _git(repo, "add", ".gitignore")
        _git(repo, "commit", "-q", "-m", "ignore build")
        (repo / "build").mkdir()
        (repo / "build" / "gen.py").write_text("def made():\n    return 1\n", encoding="utf-8")
        assert not any(p.startswith("build/") for p in sym.symbols_of_lane(repo, "main"))

    def test_the_lane_folds_the_vendored_twin_onto_its_source(self, sym, repo):
        """Dies to: the fold left out of the lane reader (a lane that synced its twin claims each
        symbol twice, under two keys)."""
        for rel in ("tools/cc/x.py", "espalier/_vendor/cc/x.py"):
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text("def k():\n    return 1\n", encoding="utf-8")
        got = sym.symbols_of_lane(repo, "main")
        assert "espalier/_vendor/cc/x.py" not in got and _named(got["tools/cc/x.py"]["symbols"]) == {"tools/cc/x.py::k"}

    def test_a_root_below_the_top_reads_top_relative_paths(self, sym, repo):
        """Run from a subdirectory, git names untracked files relative to it and diff names relative
        to the top, so one lane spoke two dialects (failure-mode review). Dies to: the reader keeping
        the root it was handed instead of the top of its tree."""
        (repo / "sub").mkdir()
        (repo / "sub" / "n.py").write_text("def k():\n    return 3\n", encoding="utf-8")
        (repo / "m.py").write_text(MOD.replace("return 1", "return 10"), encoding="utf-8")
        got = sym.symbols_of_lane(repo / "sub", "main")
        assert _named(got["sub/n.py"]["symbols"]) == {"sub/n.py::k"} and _named(got["m.py"]["symbols"]) == {"m.py::f"}, got

    def test_changed_paths_are_read_nul_separated(self, sym):
        """Dies to: `--name-only` output split on whitespace (`pkg/my file.py` becomes a path tier
        `pkg/my` and a Python `file.py` with empty sources, which is certified)."""
        seen = []

        def fake(argv, **kw):
            seen.append(argv)
            if "--name-only" in argv:
                return 0, "pkg/my file.py\0other.py\0", ""
            return 0, "", ""

        out = sym.symbols_between("base", "head", run=fake)
        assert set(out) == {"pkg/my file.py", "other.py"}, out
        assert "-z" in seen[0], seen[0]

    def test_a_moved_file_is_read_at_both_paths(self, sym, repo):
        """Dies to: rename detection left on (the move reads as one changed path, and a lane
        editing the old path meets nothing)."""
        _git(repo, "mv", "m.py", "moved.py")
        _git(repo, "commit", "-q", "-m", "move")
        got = sym.symbols_of_lane(repo, "main")
        assert {"m.py", "moved.py"} <= set(got)
        assert _named(got["m.py"]["symbols"]) == {"m.py::f", "m.py::g"}

    def test_a_base_git_cannot_read_is_a_named_refusal(self, sym, repo):
        """Dies to: a failed merge-base read as an empty lane (no symbols, so nothing meets it),
        or a refusal that names nothing (unrelated histories exit 1 with no text at all)."""
        with pytest.raises(sym.Unresolvable, match="no-such-base"):
            sym.symbols_of_lane(repo, "no-such-base")
        _git(repo, "switch", "-q", "--orphan", "unrelated")
        (repo / "x.py").write_text("X = 1\n", encoding="utf-8")
        _git(repo, "add", "x.py")
        _git(repo, "commit", "-q", "-m", "an unrelated root")
        with pytest.raises(sym.Unresolvable, match="no common history"):
            sym.symbols_of_lane(repo, "main")
