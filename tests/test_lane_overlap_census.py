# pytest-marker: default-unit -- in-process and spawn-free: the diffs come from difflib, no git
"""The symbol mapper and the pair verdict behind `scripts/lane_overlap_census.py`
(`TP-702` Task 0's oracle). Both sides of every hunk are placed, a decorator or
a comment block above a definition is the definition's, a line no node holds
is UNPLACED and never a certificate, a file that is not Python is a path tier,
mirror twins fold onto their source. In-process and spawn-free: the diffs come
from `difflib`, which writes the same `@@ -a,b +c,d @@` headers git does under
`-U0`. Each test names, in its docstring, the mutation it dies to. This file
pins the placement rules because a mapper that certified 'different functions'
where it knew nothing would silently turn an advisory into a clearance."""
from __future__ import annotations

import difflib
import importlib.util
import pathlib

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "lane_overlap_census.py"


def _load():
    spec = importlib.util.spec_from_file_location("lane_overlap_census", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_CENSUS = _load()


@pytest.fixture(scope="module")
def census():
    return _CENSUS


def _diff(old: str, new: str, path: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                        fromfile="a/" + path, tofile="b/" + path, n=0))


def _symbols(census, old: str, new: str, path: str = "p.py") -> set[str]:
    return census.changed_symbols(path, old, new, _diff(old, new, path))["symbols"]


def _placement(census, old: str, new: str, path: str = "p.py") -> dict:
    return census.changed_symbols(path, old, new, _diff(old, new, path))


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
    def test_a_changed_line_lands_on_its_function(self, census):
        """Dies to: the enclosing span read as the module for every line."""
        assert _symbols(census, OLD, OLD.replace("return x + 1", "return x + 2")) == {"p.py::f"}

    def test_a_method_is_qualified_by_its_class(self, census):
        """Dies to: the qualname prefix dropped (a bare `m`)."""
        assert _symbols(census, OLD, OLD.replace("return 1", "return 10")) == {"p.py::C.m"}

    def test_an_async_def_is_a_symbol(self, census):
        """Dies to: `ast.AsyncFunctionDef` left out of the walk (the line falls to `C`)."""
        assert _symbols(census, OLD, OLD.replace("return 2", "return 20")) == {"p.py::C.n"}

    def test_a_top_level_assignment_is_its_target_name(self, census):
        """Dies to: module-level assignments not walked (the line reads unplaced)."""
        assert _symbols(census, OLD, OLD.replace('"a": 1,', '"a": 1,\n    "b": 2,')) == {"p.py::TABLE"}

    def test_a_tuple_target_binds_each_name(self, census):
        """Dies to: the target spelled whole (`p.py::(first, second)`, a comma a step field splits on)."""
        assert _symbols(census, OLD, OLD.replace("first, second = 1, 2", "first, second = 3, 4")) == {
            "p.py::first", "p.py::second"}

    def test_a_class_body_assignment_is_the_class_s(self, census):
        """Dies to: class-body assignments made symbols of their own (`p.py::attr`)."""
        assert _symbols(census, OLD, OLD.replace("attr = 0", "attr = 1")) == {"p.py::C"}

    def test_a_pure_deletion_is_placed_in_the_old_file(self, census):
        """Dies to: deletions placed in the new file (they land on `f` or the module there)."""
        new = OLD.replace("def g(y):\n    return y - 1\n\n\n", "")
        got = _symbols(census, OLD, new)
        assert "p.py::g" in got and "p.py::f" not in got and "p.py::C" not in got, got

    def test_the_git_shaped_hunk_for_a_whole_deletion_names_only_the_deleted_def(self, census):
        """Git slides the hunk for "delete `g` whole" to the def, its body and the two blanks
        below it (`@@ -14,4 +13,0 @@`), where difflib slides it two lines up. Dies to: blank lines
        attached to the next definition (the decorated class), which named `C` beside `g`."""
        new = OLD.replace("def g(y):\n    return y - 1\n\n\n", "")
        line_of_g = OLD.splitlines().index("def g(y):") + 1
        hunk = f"@@ -{line_of_g},4 +{line_of_g - 1},0 @@\n"
        got = census.changed_symbols("p.py", OLD, new, hunk)
        assert got["symbols"] == {"p.py::g"} and got["changed"] == 2 and got["unplaced"] == 0, got

    def test_a_method_added_at_the_end_of_a_class_names_only_that_method(self, census):
        """Dies to: the blank line before the new method attached to the next top-level def."""
        new = OLD.replace("        return 2\n", "        return 2\n\n    def o(self):\n        return 4\n")
        assert _symbols(census, OLD, new) == {"p.py::C.o"}

    def test_a_trailing_comment_after_a_body_is_unplaced_not_the_next_def(self, census):
        """Dies to: a comment run that a blank line breaks still walking forward to the next def."""
        new = OLD.replace("    return x + 1\n", "    return x + 1\n# tail\n")
        got = _placement(census, OLD, new)
        assert got["symbols"] == {"p.py::<module>"} and got["unplaced"] == 1, got

    def test_a_blank_line_between_methods_names_nothing(self, census):
        """Dies to: a blank inside a class span producing the class (the two-rules finding)."""
        new = OLD.replace("        return 1\n\n    async def n", "        return 1\n\n\n    async def n")
        got = _placement(census, OLD, new)
        assert got["symbols"] == set() and got["changed"] == 0, got

    def test_a_rename_reports_both_names(self, census):
        """Dies to: only the new side of a changed hunk placed (`f` vanishes, the other lane meets nothing)."""
        assert _symbols(census, OLD, OLD.replace("def f(x):", "def f2(x):")) == {"p.py::f", "p.py::f2"}

    def test_one_hunk_that_deletes_g_and_extends_f_reports_both(self, census):
        """Dies to: the old side of a changed hunk dropped (`g`'s deletion vanishes)."""
        new = OLD.replace("    return x + 1\n\n\ndef g(y):\n    return y - 1\n", "    return x + 1\n    return x\n")
        got = _symbols(census, OLD, new)
        assert {"p.py::f", "p.py::g"} <= got, got

    def test_a_decorator_edit_is_the_definition_s(self, census):
        """Dies to: a span starting at the `def`/`class` line, not its first decorator."""
        assert _symbols(census, OLD, OLD.replace("@decorate(1)", "@decorate(2)")) == {"p.py::C"}

    def test_a_comment_block_above_a_definition_is_the_definition_s(self, census):
        """Dies to: a comment outside every node left unplaced instead of attached to the next node."""
        assert _symbols(census, OLD, OLD.replace("# the class", "# the class, renamed")) == {"p.py::C"}

    def test_a_definition_under_a_module_level_block_is_found(self, census):
        """Dies to: the walk stopping at `if`/`try` blocks (the line reads unplaced)."""
        assert _symbols(census, OLD, OLD.replace("return 3", "return 30")) == {"p.py::h"}

    def test_an_added_import_is_unplaced_and_counted(self, census):
        """Dies to: unplaced lines dropped from the symbols, or not counted."""
        got = _placement(census, OLD, OLD.replace("import os\n", "import os\nimport sys\n"))
        assert got["symbols"] == {"p.py::<module>"} and got["unplaced"] == 1 and got["changed"] == 1, got

    def test_a_file_that_is_not_python_is_a_path_tier(self, census):
        """Dies to: a prose file mapped as if it were Python (symbols by line)."""
        got = _placement(census, "a\n", "b\n", "docs/x.md")
        assert got == {"kind": "path", "symbols": {"docs/x.md"}, "changed": 0, "unplaced": 0}

    def test_unparseable_new_source_places_the_old_side_and_counts_the_new_as_unplaced(self, census):
        """Dies to: a SyntaxError on one side emptying both sides' placement."""
        new = OLD.replace("def f(x):", "def f(x")     # a lane mid-edit
        got = _placement(census, OLD, new)
        assert "p.py::f" in got["symbols"] and got["unplaced"] >= 1, got


class TestSpans:
    def test_nested_definitions_are_qualified_and_the_innermost_wins(self, census):
        """Dies to: the outermost span winning (a method's line reads as its class)."""
        nodes = census.spans(OLD)
        names = {n for n, *_ in nodes}
        assert {"LIMIT", "TABLE", "first", "second", "f", "g", "C", "C.m", "C.n", "h"} <= names
        assert "attr" not in names
        line_of_m = OLD.splitlines().index("        return 1") + 1
        assert census.enclosing(nodes, line_of_m) == "C.m"

    def test_every_diff_turns_rename_detection_off(self, census):
        """Dies to: `--no-renames` dropped (a moved file reads as added at the new path only)."""
        assert "--no-renames" in census.DIFF_ARGS


class TestPairVerdict:
    @staticmethod
    def _py(symbols, unplaced=0):
        return {"kind": "python", "symbols": set(symbols), "changed": len(symbols) + unplaced, "unplaced": unplaced}

    def test_a_shared_symbol_is_the_verdict(self, census):
        """Dies to: the shared set computed over one side only."""
        got = census.pair_verdict({"p.py": self._py({"p.py::f"})}, {"p.py": self._py({"p.py::f", "p.py::g"})})
        assert got["verdict"] == "shared symbol" and got["shared"] == ["p.py::f"]

    def test_different_functions_needs_every_line_placed_on_both_sides(self, census):
        """Dies to: unplaced lines dropped before the verdict, the review's finding: a certificate
        printed exactly where the mapper knows nothing."""
        certified = census.pair_verdict({"p.py": self._py({"p.py::f"})}, {"p.py": self._py({"p.py::g"})})
        assert certified["verdict"] == "different functions" and certified["certified"] == ["p.py"]
        blind = census.pair_verdict({"p.py": self._py({"p.py::f", "p.py::<module>"}, unplaced=1)},
                                    {"p.py": self._py({"p.py::g", "p.py::<module>"}, unplaced=1)})
        assert blind["verdict"] == "unplaced" and blind["certified"] == [], blind

    def test_a_class_on_one_side_meets_its_method_on_the_other(self, census):
        """The one rule both the claims matcher and the verdict use. Dies to: the verdict
        comparing names for equality only (the plan warns while the board certifies)."""
        got = census.pair_verdict({"p.py": self._py({"p.py::C"})}, {"p.py": self._py({"p.py::C.n"})})
        assert got["verdict"] == "shared symbol" and got["shared"] == ["p.py::C"], got
        assert census.symbols_meet({"p.py::C"}, {"p.py::C.n"}) == {"p.py::C"}
        assert census.symbols_meet({"p.py::Cx"}, {"p.py::C.n"}) == set()

    def test_a_shared_module_line_is_never_a_shared_symbol(self, census):
        """Dies to: `<module>` admitted to the shared set."""
        got = census.pair_verdict({"p.py": self._py({"p.py::<module>"}, 1)}, {"p.py": self._py({"p.py::<module>"}, 1)})
        assert got["verdict"] == "unplaced" and got["shared"] == []

    def test_prose_files_are_a_path_tier_not_a_symbol(self, census):
        """Dies to: a non-Python file counted as a shared symbol."""
        prose = {"kind": "path", "symbols": {"docs/x.md"}, "changed": 0, "unplaced": 0}
        got = census.pair_verdict({"docs/x.md": prose}, {"docs/x.md": dict(prose)})
        assert got["verdict"] == "path only" and got["paths"] == ["docs/x.md"] and got["shared"] == []

    def test_no_shared_file_is_no_verdict(self, census):
        got = census.pair_verdict({"a.py": self._py({"a.py::f"})}, {"b.py": self._py({"b.py::f"})})
        assert got["verdict"] == "none" and got["files"] == []


class TestConcurrent:
    def test_two_windows_that_overlap_are_concurrent_and_disjoint_ones_are_not(self, census):
        """Dies to: the window test inverted or one-sided."""
        a = {"created": "2026-10-16T10:00:00Z", "merged": "2026-10-16T12:00:00Z"}
        b = {"created": "2026-10-16T11:00:00Z", "merged": "2026-10-16T13:00:00Z"}
        c = {"created": "2026-10-16T12:30:00Z", "merged": "2026-10-16T14:00:00Z"}
        assert census.concurrent(a, b) and census.concurrent(b, a)
        assert not census.concurrent(a, c) and not census.concurrent(c, a)


class TestWindowLimit:
    def test_the_listing_reads_from_the_newest_number_down_to_the_window_s_floor(self, census):
        """Dies to: a fixed limit counted from the window's size (a pinned window truncates as
        merges accumulate above it, and the oldest numbers vanish with `unread: 0`)."""
        assert census.window_limit(276, 246) == 31
        assert census.window_limit(400, 180) == 221
        assert census.window_limit(5, 10) == 1
        assert census.window_limit(5000, 1) == 1000


class TestCanonical:
    def test_a_vendored_hook_folds_onto_its_source(self, census):
        """Dies to: the twin left apart (one lane meets another twice)."""
        if census._mirrors is None:
            pytest.skip("the mirror registry is not importable here")
        assert census.canonical("espalier/_vendor/cc/hooks/write_guard.py") == "tools/cc/hooks/write_guard.py"
        assert census.canonical("tools/cc/hooks/write_guard.py") == "tools/cc/hooks/write_guard.py"
        assert census.canonical("docs/HOOKS.md") == "docs/HOOKS.md"


class TestNothingReadIsNeverCertified:
    def test_a_file_with_no_counted_lines_is_unplaced_not_certified(self, census):
        """Dies to: a side with zero counted lines certified (a diff the mapper never read: an
        empty diff from a subdirectory run, a hunk header a colour config broke, a side `git show`
        could not read, a blank-only edit) printed as different functions, where git conflicts."""
        nothing = {"p.py": {"kind": "python", "symbols": set(), "changed": 0, "unplaced": 0}}
        some = {"p.py": {"kind": "python", "symbols": {"p.py::f"}, "changed": 1, "unplaced": 0}}
        assert census.pair_verdict(nothing, some)["verdict"] == "unplaced"
        assert census.pair_verdict(some, nothing)["verdict"] == "unplaced"
        assert census.pair_verdict(nothing, nothing)["verdict"] == "unplaced"

    def test_a_line_the_source_does_not_have_is_unplaced_and_counted(self, census):
        """Dies to: a line past the end of a side (a side `git show` could not read) read as a
        blank, so it counts for nothing and the file is certified."""
        got = census.changed_symbols("p.py", "", "", "@@ -0,0 +1,3 @@\n")
        assert got["changed"] == 3 and got["unplaced"] == 3, got

    def test_a_form_feed_line_does_not_shift_the_line_index(self, census):
        """Dies to: `str.splitlines()`, which also splits on form feed, U+2028 and friends where
        git and `ast` split on newlines only, so every line after one is read one off."""
        old, new = "\x0c\nimport os\n", "\x0c\nimport sys\n"
        got = census.changed_symbols("p.py", old, new, "@@ -2 +2 @@\n")
        assert got["changed"] == 2 and got["unplaced"] == 2, got

    def test_a_nul_byte_maps_nothing_without_raising(self, census):
        """Dies to: `ValueError` uncaught in `spans` (Python 3.10 raises it for a NUL byte where
        3.11 and later raise `SyntaxError`), a traceback instead of an unplaced file."""
        assert census.spans("x = 1\n\x00") == []


class TestPlacementEdges:
    def test_a_blank_line_inside_a_function_is_the_function_s(self, census):
        """Dies to: every blank line neutral, where git conflicts on the edit beside this one."""
        old = "def f(x):\n    y = x\n    return y\n\n\ndef g():\n    return 2\n"
        new = old.replace("    y = x\n", "    y = x\n\n")
        got = _placement(census, old, new)
        assert got["symbols"] == {"p.py::f"} and got["changed"] == 1 and got["unplaced"] == 0, got

    def test_a_blank_line_between_top_level_definitions_stays_neutral(self, census):
        """Dies to: a blank line outside every node handed to a neighbour."""
        old = "def f(x):\n    return x\n\n\ndef g():\n    return 2\n"
        new = old.replace("\n\n\ndef g", "\n\n\n\ndef g")
        got = _placement(census, old, new)
        assert got["symbols"] == set() and got["changed"] == 0, got

    def test_an_indented_trailing_comment_is_unplaced_not_the_next_def(self, census):
        """Dies to: the forward walk ignoring indentation, so a comment indented as `f`'s body with
        no blank before `def g` is handed to `g` (git conflicts with an edit on `f`'s last line)."""
        old = "def f():\n    return 1\n    # done\ndef g():\n    return 2\n"
        new = old.replace("# done", "# finished")
        got = _placement(census, old, new)
        assert "p.py::g" not in got["symbols"] and got["unplaced"] == 2, got

    def test_a_subscript_target_is_its_root_name(self, census):
        """Dies to: `ast.unparse` of a subscript target (`X[1, 2]`), which carries the comma the
        tuple-target test exists to keep out of a symbol."""
        old = "X = {}\nX[1, 2] = 3\n"
        assert _symbols(census, old, old.replace("= 3", "= 4")) == {"p.py::X"}


class TestSpawns:
    def test_every_spawn_runs_at_the_repo_root_with_the_binary_first(self, census, monkeypatch):
        """Dies to: `cwd` dropped (a `git diff -- path` from a subdirectory reads the pathspec
        relative to it, every diff comes back empty and every file is certified), or the binary
        built into the argv at the call site, which the subprocess-contract scanner cannot read."""
        calls = []

        class Done:
            stdout = ""

        def fake(argv, **kw):
            calls.append((argv, kw))
            return Done()

        monkeypatch.setattr(census, "run_bounded", fake)
        census._git("status")
        census._gh("pr", "list")
        assert [c[0] for c in calls] == [["git", "status"], ["gh", "pr", "list"]]
        assert all(c[1]["cwd"] == census.REPO_ROOT for c in calls), calls
        assert all(c[1]["encoding"] == "utf-8" for c in calls), calls

    def test_changed_paths_are_read_nul_separated(self, census, monkeypatch):
        """Dies to: `--name-only` output split on whitespace (`pkg/my file.py` becomes a path tier
        `pkg/my` and a Python `file.py` with empty sources, which is certified)."""
        seen = []

        def fake_git(*args):
            seen.append(args)
            return "pkg/my file.py\0other.py\0" if "--name-only" in args else ""

        monkeypatch.setattr(census, "_git", fake_git)
        out = census.symbols_between("base", "head")
        assert set(out) == {"pkg/my file.py", "other.py"}, out
        assert "-z" in seen[0], seen[0]

    def test_every_diff_reads_plain_text(self, census):
        """Dies to: a colour, external-diff or textconv setting in the box's git config turning the
        hunk header into something `HUNK_RE` does not match, so nothing is read and all is certified."""
        assert {"--no-color", "--no-ext-diff", "--no-textconv"} <= set(census.DIFF_ARGS)


class TestCanonicalFolding:
    def test_a_twin_of_a_region_host_folds_onto_the_region_s_source(self, census):
        """Dies to: one-hop folding (a region row's byte twins fold onto the region's host file,
        which itself folds onto the region's source, so one synced lane lands on two keys)."""
        if census._mirrors is None:
            pytest.skip("the mirror registry is not importable here")
        rows = census._mirrors.MIRROR_ROWS

        def base_dir(sot):
            glob = census._mirrors.glob_row_parts(sot)
            return glob[0] if glob is not None else sot

        hosts = [m for row in rows for m in row.mirrors if not m.endswith("/")]
        dirs = [(m, base_dir(row.sot)) for row in rows for m in row.mirrors if m.endswith("/")]
        pairs = [(d + host[len(sot):], host) for host in hosts for d, sot in dirs if host.startswith(sot)]
        if not pairs:
            pytest.skip("no region host under a mirrored directory in this registry")
        for twin, host in pairs:
            assert census.canonical(twin) == census.canonical(host), (twin, host)
            assert census.canonical(census.canonical(twin)) == census.canonical(twin), twin
