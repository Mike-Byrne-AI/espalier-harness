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
# slow-exempt: five scratch-repository cases of a few git calls each beside 29 in-process ones, measured 2026-10-17: 34 tests in 1.1 s on the Air
from __future__ import annotations

import difflib
import importlib.util
import pathlib
import re
import subprocess
import sys

import pytest

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
        """Dies to: the target spelled whole (`p.py::(first, second)`, a comma a step field splits on)."""
        assert _symbols(sym, OLD, OLD.replace("first, second = 1, 2", "first, second = 3, 4")) == {
            "p.py::first", "p.py::second"}

    def test_a_class_body_assignment_is_the_class_s(self, sym):
        """Dies to: class-body assignments made symbols of their own (`p.py::attr`)."""
        assert _symbols(sym, OLD, OLD.replace("attr = 0", "attr = 1")) == {"p.py::C"}

    def test_a_pure_deletion_is_placed_in_the_old_file(self, sym):
        """Dies to: deletions placed in the new file (they land on `f` or the module there)."""
        new = OLD.replace("def g(y):\n    return y - 1\n\n\n", "")
        got = _symbols(sym, OLD, new)
        assert "p.py::g" in got and "p.py::f" not in got and "p.py::C" not in got, got

    def test_the_git_shaped_hunk_for_a_whole_deletion_names_only_the_deleted_def(self, sym):
        """Git slides the hunk for "delete `g` whole" to the def, its body and the two blanks
        below it (`@@ -14,4 +13,0 @@`), where difflib slides it two lines up. Dies to: blank lines
        attached to the next definition (the decorated class), which named `C` beside `g`."""
        new = OLD.replace("def g(y):\n    return y - 1\n\n\n", "")
        line_of_g = OLD.splitlines().index("def g(y):") + 1
        hunk = f"@@ -{line_of_g},4 +{line_of_g - 1},0 @@\n"
        got = sym.changed_symbols("p.py", OLD, new, hunk)
        assert got["symbols"] == {"p.py::g"} and got["changed"] == 2 and got["unplaced"] == 0, got

    def test_a_method_added_at_the_end_of_a_class_names_only_that_method(self, sym):
        """Dies to: the blank line before the new method attached to the next top-level def."""
        new = OLD.replace("        return 2\n", "        return 2\n\n    def o(self):\n        return 4\n")
        assert _symbols(sym, OLD, new) == {"p.py::C.o"}

    def test_a_trailing_comment_after_a_body_is_unplaced_not_the_next_def(self, sym):
        """Dies to: a comment run that a blank line breaks still walking forward to the next def."""
        new = OLD.replace("    return x + 1\n", "    return x + 1\n# tail\n")
        got = _placement(sym, OLD, new)
        assert got["symbols"] == {"p.py::<module>"} and got["unplaced"] == 1, got

    def test_a_blank_line_between_methods_names_nothing(self, sym):
        """Dies to: a blank inside a class span producing the class (the two-rules finding)."""
        new = OLD.replace("        return 1\n\n    async def n", "        return 1\n\n\n    async def n")
        got = _placement(sym, OLD, new)
        assert got["symbols"] == set() and got["changed"] == 0, got

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
        assert _symbols(sym, OLD, OLD.replace("return 3", "return 30")) == {"p.py::h"}

    def test_an_added_import_is_unplaced_and_counted(self, sym):
        """Dies to: unplaced lines dropped from the symbols, or not counted."""
        got = _placement(sym, OLD, OLD.replace("import os\n", "import os\nimport sys\n"))
        assert got["symbols"] == {"p.py::<module>"} and got["unplaced"] == 1 and got["changed"] == 1, got

    def test_a_file_that_is_not_python_is_a_path_tier(self, sym):
        """Dies to: a prose file mapped as if it were Python (symbols by line)."""
        got = _placement(sym, "a\n", "b\n", "docs/x.md")
        assert got == {"kind": "path", "symbols": {"docs/x.md"}, "changed": 0, "unplaced": 0}

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
        assert {"--no-color", "--no-ext-diff", "--no-textconv", "--inter-hunk-context=0"} <= set(sym.DIFF_ARGS)


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
        assert got["symbols"] == set() and got["changed"] == 0, got

    def test_an_indented_trailing_comment_is_unplaced_not_the_next_def(self, sym):
        """Dies to: the forward walk ignoring indentation, so a comment indented as `f`'s body with
        no blank before `def g` is handed to `g` (git conflicts with an edit on `f`'s last line)."""
        old = "def f():\n    return 1\n    # done\ndef g():\n    return 2\n"
        new = old.replace("# done", "# finished")
        got = _placement(sym, old, new)
        assert "p.py::g" not in got["symbols"] and got["unplaced"] == 2, got

    def test_a_subscript_target_is_its_root_name(self, sym):
        """Dies to: `ast.unparse` of a subscript target (`X[1, 2]`), which carries the comma the
        tuple-target test exists to keep out of a symbol."""
        old = "X = {}\nX[1, 2] = 3\n"
        assert _symbols(sym, old, old.replace("= 3", "= 4")) == {"p.py::X"}


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
        assert got["m.py"]["symbols"] == {"m.py::g"}
        assert got["n.py"]["symbols"] == {"n.py::k"} and got["n.py"]["unplaced"] == 0

    def test_an_uncommitted_edit_is_placed_in_the_working_tree_s_lines(self, sym, repo):
        """The working tree adds lines above the edited function, so HEAD's text places the
        changed line on the wrong definition (code review: the edit above changed a line
        without shifting any, and a reader of HEAD's text passed it). Dies to: the new side's
        source read from HEAD instead of the working tree."""
        grown = "def e():\n    return 0\n\n\n" + MOD.replace("return 2", "return 20")
        (repo / "m.py").write_text(grown, encoding="utf-8")
        assert sym.symbols_of_lane(repo, "main")["m.py"]["symbols"] == {"m.py::e", "m.py::g"}

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
        assert got["symbols"] == {"m.py::a", "m.py::c"} and got["changed"] == 4, got

    @pytest.mark.skipif(sys.platform == "win32", reason="a POSIX shell script as the external differ")
    def test_an_external_differ_the_user_set_is_not_the_reading(self, sym, repo, tmp_path):
        """`diff.external` (a difftool's documented setup) replaced git's own diff text with
        whatever that program prints, and the edit read as nothing changed (code review,
        driven). Dies to: `--no-ext-diff` dropped from `DIFF_ARGS`."""
        silent = tmp_path / "silent-differ.sh"
        silent.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        silent.chmod(0o755)
        _git(repo, "config", "diff.external", str(silent))
        (repo / "m.py").write_text(MOD.replace("return 1", "return 10"), encoding="utf-8")
        assert sym.symbols_of_lane(repo, "main")["m.py"]["symbols"] == {"m.py::f"}

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
        assert got["m.py"]["symbols"] == {"m.py::f", "m.py::g"}

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
