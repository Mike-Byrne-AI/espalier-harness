"""`scripts/cli_cost_census.py`, the cli.py audit's instrument (TP-708a).

Every section earns its red on a frozen fixture: a `git init` tree in
`tmp_path` with a small `espalier/cli.py` committed at a fixed date, so a
reading taken from the working tree or the clock lands somewhere else. Each
test names, in its docstring, the mutation it dies to. The fixture's values and
positions disagree with a wrong reading in both directions: a shadowed local
that must give no edge beside a load that must, and a working-tree edit that
must not be read beside the committed text that must."""
# slow-exempt: a few `git init`/`commit` spawns per test in tmp_path, measured under 2 s for the module; the collision and
# lane_read classes build small branch histories (about 30 spawns the largest), each test measured under 3 s
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "cli_cost_census.py"


def _load():
    spec = importlib.util.spec_from_file_location("_cli_cost_census_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_CENSUS = _load()

#: The fixture's commit date: far from any wall clock this suite runs at, so a
#: window read from the clock cannot land on it.
_PINNED = "2020-01-02T03:04:05+00:00"

_CLI_FIXTURE = '''\
import os
from espalier import doctor as _doctor

_LATCH = False
_MEMO = {}
TABLE = {"alpha": None}


def _helper():
    return 1


def _setter():
    global _LATCH
    _LATCH = True


def _reader():
    return _LATCH


def cmd_alpha(args):
    _setter()
    _MEMO["k"] = 1
    return _helper() + len(getattr(os, "sep")) + _doctor.check()


def cmd_beta(args):
    _helper = 3
    return _reader() + _helper


def build_parser():
    parser = object()
    parser.set_defaults(func=cmd_alpha)
    return parser


class Thing:
    def method(self):
        from espalier import fuse
        return fuse, _helper()
'''


def _git_env() -> dict[str, str]:
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_NAME="fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid",
               GIT_COMMITTER_NAME="fixture", GIT_COMMITTER_EMAIL="fixture@example.invalid",
               GIT_AUTHOR_DATE=_PINNED, GIT_COMMITTER_DATE=_PINNED, GIT_TERMINAL_PROMPT="0")
    return env


def _git(repo: pathlib.Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=_git_env(), check=True, timeout=45)
    return proc.stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "espalier").mkdir(parents=True)
    (root / "espalier" / "cli.py").write_text(_CLI_FIXTURE, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "espalier/cli.py")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "fixture")
    monkeypatch.chdir(root)
    return root


def _head(repo: pathlib.Path) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()


class TestThePinIsRequiredAndReadFromTheCommit:
    def test_a_run_without_at_refuses(self, repo, capsys):
        """Dies to: `--at` given a default (`origin/main`, HEAD), so a run reads whatever the
        checkout holds that day."""
        with pytest.raises(SystemExit) as exc:
            _CENSUS.main(["functions", "--root", str(repo)])
        assert exc.value.code == 2
        assert "--at" in capsys.readouterr().err

    def test_the_window_ends_at_the_commit_date_not_the_clock(self, repo):
        """Dies to: the window read from the wall clock (`now - 30 days`) instead of the pin's
        commit date: the fixture's date is in 2020, so a clock window misses it by years."""
        pin = _CENSUS.resolve_pin(repo, _head(repo))
        assert pin["date"] == "2020-01-02T03:04:05Z"
        assert pin["window"] == {"days": 30, "since": "2019-12-03T03:04:05Z", "until": "2020-01-02T03:04:05Z"}
        assert pin["at"] == _head(repo)

    def test_a_short_pin_resolves_to_the_full_object_id(self, repo):
        """Dies to: the pin recorded as typed, so two runs at `abc123` and at its full id read as
        two pins."""
        full = _head(repo)
        assert _CENSUS.resolve_pin(repo, full[:9])["at"] == full

    def test_the_source_is_the_commit_s_not_the_working_tree(self, repo):
        """Dies to: cli.py read from the working tree: an uncommitted function added after the pin
        would be counted at it."""
        at = _head(repo)
        path = repo / "espalier" / "cli.py"
        path.write_text(path.read_text(encoding="utf-8") + "\n\ndef cmd_gamma(args):\n    return 0\n",
                        encoding="utf-8")
        _CENSUS.source_at.cache_clear()
        out = _CENSUS.census(repo, at, ["functions"])
        assert out["functions"]["commands"] == ["cmd_alpha", "cmd_beta"]


class TestTheFunctionsGraph:
    @pytest.fixture
    def section(self, repo):
        _CENSUS.source_at.cache_clear()
        return _CENSUS.census(repo, _head(repo), ["functions"])["functions"]

    @pytest.fixture
    def graph(self, repo):
        _CENSUS.source_at.cache_clear()
        tree, defs = _CENSUS.parse_cli(repo, _head(repo))
        return _CENSUS.graph(tree, defs)

    def test_the_counts_cover_functions_classes_and_module_names(self, section):
        """Dies to: module-level names or classes left out of the definitions (the sum of Task 2
        would then miss them), or an import counted as a definition."""
        assert (section["functions"], section["classes"], section["module_names"]) == (6, 1, 3)
        assert section["definitions"] == 10
        assert section["public_functions"] == 3

    def test_a_global_write_is_an_edge_so_the_latch_keeps_its_writer(self, section, graph):
        """Dies to: the write edge of a `global` dropped, so `_LATCH` is tied to its reader alone
        and a unit could move `_setter` without it."""
        assert graph["writes"] == {"_setter": ["_LATCH"]}
        assert "_LATCH" in graph["edges"]["_setter"]
        assert section["latches"] == {"_LATCH": {"writers": ["_setter"], "readers": ["_reader"]}}

    def test_a_memo_changed_in_place_names_the_function_that_changes_it(self, section):
        """Dies to: a subscript store on a module dict read as a plain load, so the memo has no
        writer and moves apart from the function that fills it."""
        assert section["memos"] == {"_MEMO": {"writers": ["cmd_alpha"], "readers": ["cmd_alpha"]}}

    def test_a_shadowed_local_is_no_edge_and_a_real_load_is_one(self, graph):
        """Dies to: every `ast.Name` load counted as an edge, so `cmd_beta`'s local `_helper`
        ties it to the module's `_helper`; or locals over-excluded, so `cmd_alpha` loses it."""
        assert "_helper" not in graph["edges"]["cmd_beta"]
        assert "_reader" in graph["edges"]["cmd_beta"]
        assert "_helper" in graph["edges"]["cmd_alpha"]

    def test_the_parser_s_dispatch_wiring_is_an_edge(self, graph):
        """Dies to: `set_defaults(func=...)` keyword values skipped, so `build_parser` reaches no
        command and every command reads as reached by nothing."""
        assert graph["edges"]["build_parser"] == ["cmd_alpha"]

    def test_what_the_graph_cannot_read_is_counted_not_dropped(self, section, graph):
        """Dies to: a `getattr` with a constant name, a call through an imported module or a lazy
        import inside a definition silently left out of the counts."""
        assert section["unresolved"]["getattr"] == 1
        assert section["unresolved"]["through_module"] == 1
        assert graph["unresolved"]["Thing"]["lazy_imports"] == [
            {"module": "espalier", "names": ["fuse"], "line": 41}]

    def test_the_json_carries_the_pin_and_an_empty_unread(self, repo, capsys):
        """Dies to: the pin left out of a named-section run, so a figure cannot be tied to the
        commit it was read at."""
        assert _CENSUS.main(["functions", "--at", _head(repo), "--root", str(repo), "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["pin"]["at"] == _head(repo)
        assert out["unread"] == {}


class TestTheLayerView:
    """The fixture's layers, seeded by hand: `low` is `_reader` (which loads `_LATCH`), `mid`
    is `_setter` (which writes it). The latch's reader and writer then sit in two layers."""

    _SEEDS = (("low", ("_reader",)), ("mid", ("_setter", "_gone")))

    @pytest.fixture
    def section(self, repo):
        _CENSUS.source_at.cache_clear()
        return _CENSUS.census(repo, _head(repo), ["layers"], extra={"layer_seeds": self._SEEDS})["layers"]

    def test_a_latch_whose_reader_and_writer_sit_in_two_layers_is_named(self, section):
        """Dies to: the layers closed downward and nothing more, so a layer move takes the latch
        and its reader and leaves its writer behind, writing a `global` that is now another
        module's."""
        assert section["split_ties"] == [{"tie": "_LATCH", "kind": "latch", "home": "low",
                                          "held": {"_reader": "low", "_setter": "mid"}}]

    def test_a_layer_pulled_to_hold_its_ties_names_what_it_pulls(self, section):
        """Dies to: the tie-closed size read as the downward closure, so the unit that keeps the
        latch whole is priced as the one that splits it."""
        low = section["layers"][0]
        assert low["members"] == ["_LATCH", "_reader"]
        assert low["tie_closed"]["pulled"] == ["_setter"]
        assert low["tie_closed"]["functions"] == 2

    def test_a_name_reached_only_by_a_write_is_counted_apart(self, repo):
        """Dies to: write edges dropped from the layer's closure (then a layer holds no latch it
        only sets), or the loads-only count left out, so a figure read on loads alone (the
        pack's 6 names for the interpreter core) cannot be reconciled with this one (8)."""
        _CENSUS.source_at.cache_clear()
        seeds = (("writer", ("_setter",)),)
        out = _CENSUS.census(repo, _head(repo), ["layers"], extra={"layer_seeds": seeds})["layers"]
        layer = out["layers"][0]
        assert layer["members"] == ["_LATCH", "_setter"]
        assert (layer["names"], layer["loads_only"]["names"]) == (1, 0)

    def test_a_seed_absent_at_the_pin_is_named_not_dropped(self, section):
        """Dies to: a hand seed that no longer exists silently skipped, so a renamed function
        empties its layer with nothing said (the settings seeds did, at 3330a5a)."""
        assert section["layers"][1]["missing_seeds"] == ["_gone"]

    def test_a_layer_whose_closure_swallows_a_higher_seed_says_so(self, repo):
        """Dies to: a higher layer's seed absorbed into a lower layer's closure in silence, so
        the bottom-up order reads closed while the higher layer is empty by construction."""
        _CENSUS.source_at.cache_clear()
        seeds = (("low", ("cmd_beta",)), ("mid", ("_reader",)))
        out = _CENSUS.census(repo, _head(repo), ["layers"], extra={"layer_seeds": seeds})["layers"]
        assert out["layers"][0]["absorbed_seeds"] == ["_reader"]
        assert out["layers"][1]["members"] == []


class TestOwnershipFollowsTheCommands:
    @pytest.fixture
    def section(self, repo):
        _CENSUS.source_at.cache_clear()
        return _CENSUS.census(repo, _head(repo), ["clusters"], extra={"concerns": {}})["clusters"]

    def test_the_parser_is_unreached_by_a_command_and_named_as_the_entry(self, section):
        """Dies to: `build_parser` made a root of its own, so the parser's functions read as
        owned and the unreached count drops below the pack's (98/197/15 at 17d83e0 is with the
        commands alone as roots)."""
        by = section["by_command"]
        assert "<entry>" not in by["per_root"]
        assert by["unreached_entry"] == ["build_parser"]
        assert by["unreached_dead"] == ["TABLE", "Thing"]

    def test_the_functions_alone_are_split_beside_every_definition(self, section):
        """Dies to: only the all-definitions split printed, so a figure read over functions (the
        pack's) cannot be told from one read over functions, classes and names."""
        by = section["by_command"]
        assert by["functions"] == {"owned": 5, "shared": 0, "unreached": 1}
        assert (by["owned"]["definitions"], by["shared"]["definitions"],
                by["unreached"]["definitions"]) == (6, 1, 3)

    def test_a_concern_s_owned_part_is_told_from_its_reach(self, repo):
        """Dies to: the concern's size read as everything its commands reach, so a function a
        command outside it also calls (here `_reader`, shared with `cmd_gamma`) is priced as the
        concern's own. The pack's 225 functions at 17d83e0 is the owned part; the reach is 249."""
        path = repo / "espalier" / "cli.py"
        path.write_text(_CLI_FIXTURE + "\n\ndef cmd_gamma(args):\n    return _reader()\n", encoding="utf-8")
        _git(repo, "add", "espalier/cli.py")
        _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "gamma")
        _CENSUS.source_at.cache_clear()
        out = _CENSUS.census(repo, _head(repo), ["clusters"],
                             extra={"concerns": {"pair": ("cmd_alpha", "cmd_beta")}})["clusters"]
        size = out["concerns"]["concern_size"]["pair"]
        assert size["reach"]["functions"] == 5
        assert size["owned"]["functions"] == 4
        assert size["owned"]["share_of_file_lines"] == round(size["owned"]["function_lines"] / out["file_lines"], 3)


class TestTheImporters:
    """A second module and a test import cli, each in a spelling the other lacks."""

    _OTHER = '''\
from espalier import cli as _cli


def run():
    from espalier.cli import _reader
    return _cli.TABLE, _reader()
'''
    _TEST = "from espalier.cli import Thing\n"

    @pytest.fixture
    def importing(self, repo):
        (repo / "espalier" / "other.py").write_text(self._OTHER, encoding="utf-8")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_x.py").write_text(self._TEST, encoding="utf-8")
        (repo / "docs").mkdir()
        (repo / "docs" / "RUN.md").write_text("python -m espalier.cli init .\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "importers")
        _CENSUS.source_at.cache_clear()
        return repo

    def test_both_spellings_are_read_and_tests_kept_apart(self, importing):
        """Dies to: the attributes loaded through `from espalier import cli as _cli` left out
        (then `TABLE` is no import), or the tests' imports counted with another module's."""
        out = _CENSUS.census(importing, _head(importing), ["importers"])["importers"]
        assert out["outside_tests"]["by_file"] == {
            "espalier/other.py": {"names": ["TABLE", "_reader"], "lazy": True, "sites": 2, "test": False}}
        assert out["tests"] == {"files": 1, "distinct_names": 1}

    def test_a_module_run_is_classed_by_where_it_lives(self, importing):
        """Dies to: every `-m espalier.cli` mention counted as a run no move may change, so a doc
        an adopter reads and a dated record read as one population."""
        runs = _CENSUS.census(importing, _head(importing), ["importers"])["importers"]["entry_points"]["module_run"]
        assert runs["docs"] == {"files": 1, "paths": ["docs/RUN.md"]}
        assert runs["code"]["files"] == 0

    def test_another_module_s_import_takes_a_name_out_of_the_dead(self, importing):
        """Dies to: the importers read never fed into ownership, so `TABLE` (read by another
        module) and `Thing` (by a test alone) read as dead beside each other."""
        by = _CENSUS.census(importing, _head(importing), ["clusters"], extra={"concerns": {}})["clusters"]["by_command"]
        assert by["unreached_external"] == ["TABLE"]
        assert by["unreached_tests_only"] == ["Thing"]
        assert by["unreached_dead"] == []


class TestThePatches:
    """A test file that patches cli in every spelling, and patches another module once."""

    _TEST = '''\
from espalier import cli
from espalier import doctor as other


def test_it(monkeypatch):
    monkeypatch.setattr(cli, "_helper", lambda: 2)
    monkeypatch.setattr(cli, "_LATCH", True, raising=False)
    monkeypatch.setattr("espalier.cli._reader", lambda: 0)
    monkeypatch.setattr(cli, "_doctor", None)
    monkeypatch.setattr(cli.os, "sep", "/")
    monkeypatch.setattr(other, "_helper", None)
    cli.TABLE = {}
'''

    @pytest.fixture
    def section(self, repo):
        (repo / "tests").mkdir()
        (repo / "tests" / "test_patching.py").write_text(self._TEST, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "patches")
        _CENSUS.source_at.cache_clear()
        return _CENSUS.census(repo, _head(repo), ["patches"])["patches"]

    def test_every_spelling_of_a_patch_on_cli_is_a_site_and_no_other_module_s(self, section):
        """Dies to: a string target or an assignment dropped (the reasoning review's 146 against
        149 at 17d83e0 was the setattr sites alone), or a patch on another module counted."""
        assert (section["files"], section["sites"], section["targets"]) == (1, 5, 5)
        assert section["by_kind"] == {"assign": 1, "setattr": 4}
        assert section["string_targets"] == 1

    def test_a_patch_through_cli_on_another_module_is_counted_apart(self, section):
        """Dies to: `setattr(cli.os, ...)` read as a patch of a cli name `os`, or dropped."""
        assert section["through_cli"] == {"sites": 1, "targets": ["os.sep"]}

    def test_loaders_imported_targets_and_raising_false_are_named(self, section):
        """Dies to: the loader count read as a yes/no (then `_helper`, loaded by `cmd_alpha` and
        `Thing` but shadowed in `cmd_beta`, reads as one loader), a name cli imports read as
        its own, or a `raising=False` site uncounted."""
        assert section["per_target"]["_helper"] == {"sites": 1, "loaders": 2}
        assert section["more_than_one_loader"] == {"targets": 1, "sites": 1}
        assert section["imported_into_cli"]["names"] == ["_doctor"]
        assert section["no_loader"] == ["TABLE"]
        assert section["raising_false"] == {"_LATCH": {"sites": 1, "raising_false": 1}}


def _add(repo: pathlib.Path, files: dict[str, str], message: str = "files") -> None:
    for rel, text in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)
    _CENSUS.source_at.cache_clear()


class TestTheReadersByPath:
    """A test file that reads cli.py by path in each spelling, inside and outside the spans a
    hand list classes; a script that names it; a file outside tests/ and scripts/ that does too."""

    _READS = '''\
"""Reads espalier/cli.py: a docstring names the path and reads nothing."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT / "espalier" / "cli.py"
KEYS = {("espalier/cli.py", "_helper"): 1, ("espalier/cli.py", "TABLE"): 2}
PAIR = ("espalier/cli.py", "espalier/doctor.py")
SCANNED = ("espalier/cli.py", "espalier/other.py")


def test_silent():
    src = (ROOT / "espalier" / "cli.py").read_text()  # espalier/cli.py in a comment reads nothing
    assert "x" not in src


def test_through_a_name():
    assert "y" not in CLI_PATH.read_text()


class TestLoud:
    def test_loud(self):
        assert (ROOT / "espalier/cli.py").exists()
'''
    _HAND = (("tests/test_reads.py", "test_silent", "silent"),
             ("tests/test_reads.py", "SCANNED", "silent"),
             ("tests/test_reads.py", "test_through_a_name", "silent"),
             ("tests/test_flat.py", None, "flat-module"),
             ("tests/test_gone.py", "test_x", "silent"))

    @pytest.fixture
    def section(self, repo):
        _add(repo, {"tests/test_reads.py": self._READS,
                    "tests/test_flat.py": 'import glob\nFILES = glob.glob("espalier/*.py")\n',
                    "scripts/s.py": 'CLI = "espalier/cli.py"\n',
                    "bench/b.py": 'CLI = "espalier/cli.py"\n'})
        return _CENSUS.census(repo, _head(repo), ["readers"], extra={"reader_classes": self._HAND})["readers"]

    def test_each_spelling_is_one_site_and_a_comment_or_a_docstring_none(self, section):
        """Dies to: a `/ "cli.py"` join missed (path_join 0), a key's first element counted again
        as a path literal (4 read as 6), a 2-tuple of two paths read as a symbol key (2 read as
        4), or a file outside tests/ and scripts/ scanned (bench/b.py's literal counted)."""
        assert section["by_kind"] == {"symbol_key": {"sites": 2, "files": 1},
                                      "path_literal": {"sites": 4, "files": 2},
                                      "path_join": {"sites": 2, "files": 1}}
        assert section["keyed_symbols"] == ["TABLE", "_helper"]
        assert section["beside"]["literals_with_key_elements"] == {"sites": 6, "files": 2}
        assert section["beside"]["keys_any_second_element"] == {"sites": 4, "files": 1}

    def test_a_site_in_a_hand_listed_span_takes_its_class_and_the_rest_are_loud(self, section):
        """Dies to: the hand list's spans not read (every site loud, silent reads 0), or every
        site in a listed file classed by the file (the loud sites of test_reads.py read silent)."""
        assert section["by_class"]["silent"] == {"symbol_key": {"sites": 0, "files": 0},
                                                 "path_literal": {"sites": 1, "files": 1},
                                                 "path_join": {"sites": 1, "files": 1}}
        assert section["by_class"]["loud"] == {"symbol_key": {"sites": 2, "files": 1},
                                               "path_literal": {"sites": 3, "files": 2},
                                               "path_join": {"sites": 1, "files": 1}}

    def test_a_hand_entry_is_checked_at_the_pin_and_a_gone_one_is_named(self, section):
        """Dies to: a listed reader gone at the pin dropped in silence, a flat reader with no
        site of its own dropped as absent, or a test that reads through a module-level name
        reported with nothing said of the name."""
        entries = {(e["path"], e["symbol"]): e for e in section["hand"]["entries"]}
        assert section["hand"]["classified_by"] == "hand"
        assert section["hand"]["missing"] == ["tests/test_gone.py::test_x"]
        assert entries[("tests/test_flat.py", None)]["exists"] is True
        assert entries[("tests/test_flat.py", None)]["sites"] == 0
        assert entries[("tests/test_reads.py", "test_through_a_name")]["sites"] == 0
        assert entries[("tests/test_reads.py", "test_through_a_name")]["via"] == ["CLI_PATH"]
        assert entries[("tests/test_reads.py", "test_silent")]["sites"] == 1


#: The sweep's rule as it reads at 3330a5a, frozen: the census ports it and pins its text by
#: digest, so a fixture that holds anything else reads unread.
_SWEEP_COPY = r'''import re

from espalier.surface_contract import is_shipped_pack

_CODESPAN_RE = re.compile(r"`[^`]*`")
_RECORD_SURFACE_DOCS = frozenset({
    "docs/session-archive.md",
})
_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
_STRUCK_SPAN_RE = re.compile(r"~~`[^`]+`~~")
_ROW_NUMBER_CELL_MAX = 8


def _is_struck_row(line: str) -> bool:
    stripped = line.lstrip(" ")
    if len(line) - len(stripped) > 3 or not stripped.startswith("|"):
        return False
    for cell in _CELL_SPLIT_RE.split(stripped)[1:3]:
        spans = _CODESPAN_RE.findall(cell)
        if spans:
            return len(_STRUCK_SPAN_RE.findall(cell)) == len(spans)
        if len(cell.strip()) > _ROW_NUMBER_CELL_MAX:
            return False
    return False


def _swept_docs(tracked: set[str]) -> list[str]:
    """The sweep's population, as at 3330a5a (its docstring cut)."""
    return sorted(
        p for p in tracked
        if p.endswith(".md")
        and (
            p.startswith(("docs/", "memory/", "changelog.d/"))
            or "/" not in p
            or (p.startswith("task-packs/") and not is_shipped_pack(p))
        )
        and p not in _RECORD_SURFACE_DOCS
    )
'''

_CONTRACT_COPY = r'''import fnmatch

SHIPPED_PACK_DIRS: tuple[str, ...] = ("task-packs", "task-packs/Deferred")
_PACK_FILENAME_PATTERN = "TP-*.md"


def _normalize(rel_path: str) -> str:
    p = rel_path.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def is_shipped_pack(rel_path: str) -> bool:
    p = _normalize(rel_path)
    parent, _, name = p.rpartition("/")
    return parent in SHIPPED_PACK_DIRS and fnmatch.fnmatchcase(name, _PACK_FILENAME_PATTERN)
'''

_CITING = {
    "tests/test_doc_source_citations.py": _SWEEP_COPY,
    "espalier/surface_contract.py": _CONTRACT_COPY,
    "task-packs/ledger.d/DEF-1.md": ("<!-- class: §C0 -->\n"
                                     "| ~~`DEF-1`~~ | `espalier/cli.py::_helper` | closed; it cited `cli.py::_reader` |\n"
                                     "| ~~`DEF-1`~~ | §C0 | `espalier/cli.py::_helper` |\n"),
    "task-packs/ledger.d/DEF-2.md": ("<!-- class: §C0 -->\n"
                                     "| `DEF-2` | `espalier/cli.py::cmd_alpha` near espalier/cli.py:12 | the body cites "
                                     "`cli.py::_setter` and espalier.cli._LATCH |\n"
                                     "| `DEF-2` | §C0 | `espalier/cli.py::cmd_alpha` |\n"),
    "docs/GUIDE.md": ("See `espalier/cli.py::TABLE`, `tests/test_cli.py::test_x` and `espalier.cli.main`.\n\n"
                      "| ~~`DEF-9`~~ | `espalier/cli.py::gone` | a closed row kept in a doc |\n"),
    "docs/session-archive.md": "Found `espalier/cli.py::old` then.\n",
    "task-packs/TP-9-plan.md": "Move `espalier/cli.py::cmd_beta`.\n",
    "tools/cc/hook.py": "# reads espalier/cli.py::TABLE\nX = 1\n",
    "espalier/_vendor/cc/hook.py": "# reads espalier/cli.py::TABLE\nX = 1\n",
    "scripts/x.py": "# see cli.py::_helper\n",
    "bench/corpus/a.json": '{"cmd": "espalier/cli.py::build_parser"}\n',
    ".claude/commands/c.md": "Edit `espalier/cli.py::cmd_alpha`.\n",
    "README.md": "Run `python -m espalier.cli init` or call `espalier.cli.main`.\n",
}


def _occ(part: dict) -> dict[str, int]:
    return {s: part[s]["occurrences"] for s in _CENSUS.CITATION_SPELLINGS}


class TestTheCitations:
    """Every surface a citation of cli.py lives on, one file each, the four spellings spread
    over them so a count read off the wrong surface or the wrong spelling lands elsewhere."""

    @pytest.fixture
    def section(self, repo):
        _add(repo, _CITING)
        return _CENSUS.census(repo, _head(repo), ["citations"])["citations"]

    def test_a_struck_row_s_citation_is_struck_and_a_live_one_live(self, section):
        """Dies to: a struck ledger fragment's citation counted as live (the live fragments read
        4, not 2), or a line the sweep skips as a closed row counted live in its doc."""
        split = section["split"]
        assert _occ(split["struck"]["struck_fragments"]) == {"path_symbol": 2, "bare_symbol": 1, "line": 0, "dotted": 0}
        assert _occ(split["swept_live"]["live_fragments"]) == {"path_symbol": 2, "bare_symbol": 1, "line": 1,
                                                               "dotted": 1}
        assert _occ(split["struck"]["struck_lines_in_swept_docs"])["path_symbol"] == 1
        assert _occ(split["swept_live"]["docs"]) == {"path_symbol": 1, "bare_symbol": 0, "line": 0, "dotted": 2}
        assert split["swept_live"]["docs"]["paths"] == ["README.md", "docs/GUIDE.md"]
        assert section["fragments"] == {"all": 2, "struck": 1}

    def test_the_bare_spelling_is_counted_and_a_longer_name_is_not_it(self, section):
        """Dies to: the bare `cli.py::` spelling missed (0), or read without its left boundary,
        so `espalier/cli.py::` and `tests/test_cli.py::` count as bare too (16, not 3)."""
        assert section["totals"]["bare_symbol"] == {"occurrences": 3, "files": 3}
        assert section["totals"]["path_symbol"] == {"occurrences": 12, "files": 9}
        assert section["totals"]["dotted"]["occurrences"] == 3
        assert section["totals"]["line"]["occurrences"] == 1

    def test_the_record_the_unchecked_and_the_protected_zone_are_apart(self, section):
        """Dies to: the record set typed here instead of read from the pin, a pack read as a
        swept doc, or a protected-zone file read without its vendored twin beside it."""
        split = section["split"]
        assert section["record_set"] == ["docs/session-archive.md"]
        assert split["record"]["record_set"]["path_symbol"]["occurrences"] == 1
        unchecked = {p: v["path_symbol"]["occurrences"] for p, v in split["unchecked_live"].items()}
        assert unchecked == {"packs": 1, "bench_corpus": 1, "claude_bodies": 1, "code": 0, "other": 0}
        assert split["unchecked_live"]["code"]["bare_symbol"]["occurrences"] == 1
        assert split["protected_zone"]["by_file"] == [
            {"path": "tools/cc/hook.py", "occurrences": {"path_symbol": 1}, "twin": "espalier/_vendor/cc/hook.py",
             "twin_in_tree": True, "twin_occurrences": {"path_symbol": 1}}]
        assert section["unread"] == {}

    def test_a_sweep_whose_rule_changed_at_the_pin_reads_its_split_unread(self, repo):
        """Dies to: the sweep's rule taken on trust where its text differs from the one ported
        (a changed `_swept_docs` read as the old one), so a population it no longer reads is
        reported as swept."""
        changed = _SWEEP_COPY.replace('("docs/", "memory/", "changelog.d/")', '("docs/", "memory/", "bench/")')
        _add(repo, {**_CITING, "tests/test_doc_source_citations.py": changed})
        out = _CENSUS.census(repo, _head(repo), ["citations"])["citations"]
        assert out["split"]["swept_live"] is None and out["split"]["unchecked_live"] is None
        assert "tests/test_doc_source_citations.py::_swept_docs" in out["unread"]["swept_live"]
        assert out["split"]["struck"]["struck_fragments"]["path_symbol"]["occurrences"] == 2


_PROBES = {
    "task-packs/probes.d/DEF-1.json": json.dumps({
        "id": "DEF-1", "subject": "espalier/cli.py", "open_value": "True",
        "cmd": "python3 -c \"import ast; t=ast.parse(open('espalier/cli.py').read()); "
               "print(any(getattr(n,'name','')=='_setter' for n in ast.walk(t)))\""}),
    "task-packs/probes.d/DEF-2.json": json.dumps({
        "id": "DEF-2", "subject": "docs/x.md", "open_value": "1",
        "cmd": "python -c 'from espalier import cli; print(cli._reader())'"}),
    "task-packs/probes.d/DEF-3.json": json.dumps({
        "id": "DEF-3", "subject": "espalier/cli.py", "cmd": None, "why_not": "no local oracle"}),
    "task-packs/probes.d/DEF-4.json": json.dumps({
        "id": "DEF-4", "subject": "espalier/other.py", "cmd": "python3 -c \"print('cli is fine')\""}),
    "task-packs/probes.d/DEF-5.json": json.dumps({
        "id": "DEF-5", "subject": "docs/y.md",
        "cmd": "python3 -c \"import subprocess, sys; from espalier import cli; cli._helper = None; "
               "subprocess.run([sys.executable, '-m', 'espalier', 'init'])\""}),
    "task-packs/probes.d/README.md": "probes, one file per row; espalier/cli.py\n",
    "task-packs/ledger.d/DEF-1.md": "<!-- -->\n| `DEF-1` | espalier/cli.py | live |\n",
    "task-packs/ledger.d/DEF-2.md": "<!-- -->\n| ~~`DEF-2`~~ | docs/x.md | struck |\n",
    "task-packs/ledger.d/DEF-3.md": "<!-- -->\n| `DEF-3` | espalier/cli.py | live |\n",
}


class TestTheProbes:
    @pytest.fixture
    def section(self, repo):
        _add(repo, _PROBES)
        out = _CENSUS.census(repo, _head(repo), ["probes"], extra={"concerns": {}})["probes"]
        return out, {r["id"]: r for r in out["rows"]}

    def test_a_probe_reads_cli_by_its_path_its_import_or_its_subject_and_not_by_the_word(self, section):
        """Dies to: a probe counted by the word `cli` in its text (DEF-4 prints a string), or the
        README in the probes folder read as a probe."""
        out, rows = section
        assert sorted(rows) == ["DEF-1", "DEF-2", "DEF-3", "DEF-5"]
        assert out["probes"] == 5
        assert (out["reading_cli"], out["subject_only"]) == (3, 1)
        assert rows["DEF-1"]["by"] == ["subject", "path"]
        assert rows["DEF-5"]["by"] == ["import", "patch", "run"]
        assert rows["DEF-3"]["by"] == ["subject"] and rows["DEF-3"]["has_cmd"] is False

    def test_a_struck_row_s_probe_is_struck_and_a_missing_row_is_named(self, section):
        """Dies to: the row's state read from the fragment's presence alone (DEF-2's struck row
        read live), or a probe with no row given a state it does not have."""
        out, rows = section
        assert (rows["DEF-1"]["row"], rows["DEF-2"]["row"], rows["DEF-5"]["row"]) == ("live", "struck", "no row")
        assert out["by_row"] == {"live": 2, "struck": 1, "no row": 1}
        assert out["live_reading_cli"] == 1

    def test_each_probe_names_its_symbols_and_their_owners(self, section):
        """Dies to: an AST read's symbol (`getattr(n, 'name', '') == '_setter'`) dropped, so the
        probe reads as naming nothing a move could take; or the owner read off the wrong command."""
        _out, rows = section
        assert rows["DEF-1"]["symbols"] == ["_setter"]
        assert rows["DEF-1"]["owners"]["_setter"]["owned_by"] == "cmd_alpha"
        assert rows["DEF-2"]["symbols"] == ["_reader"] and rows["DEF-2"]["commands"] == ["cmd_beta"]
        assert rows["DEF-5"]["symbols"] == ["_helper"]


_ROWS = {
    "task-packs/ledger.d/DEF-10.md": "<!-- -->\n| `DEF-10` | `.gitignore` vs `espalier/cli.py::_helper` | body |\n",
    "task-packs/ledger.d/DEF-11.md": ("<!-- -->\n| `DEF-11` | espalier/cli.py::cmd_alpha; docs/x.md | the body cites "
                                      "`espalier/cli.py::_setter` |\n"),
    "task-packs/ledger.d/DEF-12.md": "<!-- -->\n| `DEF-12` | docs/x.md then espalier/cli.py | body |\n",
    "task-packs/ledger.d/DEF-13.md": "<!-- -->\n| ~~`DEF-13`~~ | espalier/cli.py::_reader | closed |\n",
    "task-packs/ledger.d/DEF-14.md": "<!-- -->\n| `DEF-14` | docs/y.md | the fix edits `espalier/cli.py::_reader` |\n",
    "task-packs/ledger.d/DEF-15.md": ("<!-- -->\n| `DEF-15` | docs/y.md | mentions `cli.py::TABLE` and espalier/cli.py "
                                      "by path |\n"),
    "task-packs/ledger.d/DEF-16.md": "<!-- -->\n| ~~`DEF-16`~~ | docs/z.md | `espalier/cli.py::_helper` |\n",
    "task-packs/ledger.d/DEF-17.md": ("<!-- -->\n| `DEF-17` | docs/w.md | a body with a \\| pipe, then "
                                      "`espalier/cli.py::TABLE` |\n"),
}


class TestTheLedgerTiers:
    @pytest.fixture
    def section(self, repo):
        _add(repo, _ROWS)
        return _CENSUS.census(repo, _head(repo), ["ledger_rows"], extra={"concerns": {}})["ledger_rows"]

    def test_a_struck_id_cell_is_in_no_tier(self, section):
        """Dies to: a struck id cell (`~~`) read as live: DEF-13 joins tiers 1 and 2 and DEF-16
        tier 3."""
        assert (section["fragments"], section["struck"], section["live"]) == (8, 2, 6)
        assert [r["id"] for r in section["tier2"]["rows"]] == ["DEF-10", "DEF-11", "DEF-12"]
        assert [r["id"] for r in section["tier3"]["rows"]] == ["DEF-14"]

    def test_the_first_path_token_reads_a_dotfile_both_ways(self, section):
        """Dies to: the tokenizer's dotfile rule not stated (`.gitignore` taken as DEF-10's first
        path in both readings, or in neither), or the first token taken whatever it is (DEF-12's
        `docs/x.md` comes first)."""
        tier1 = section["tier1"]
        assert tier1["dotfile_not_counted"] == {"count": 2, "ids": ["DEF-10", "DEF-11"]}
        assert tier1["dotfile_counted"] == {"count": 1, "ids": ["DEF-11"]}
        assert tier1["differ"] == ["DEF-10"]

    def test_each_row_names_its_symbols_and_their_owners(self, section):
        """Dies to: the symbols read from the site cell alone (DEF-11's body cites `_setter`), or
        the owner taken from the wrong command."""
        rows = {r["id"]: r for r in section["tier2"]["rows"] + section["tier3"]["rows"]}
        assert rows["DEF-11"]["symbols"] == ["_setter", "cmd_alpha"]
        assert rows["DEF-11"]["commands"] == ["cmd_alpha"]
        assert rows["DEF-12"]["symbols"] == []
        assert rows["DEF-14"]["owners"]["_reader"]["owned_by"] == "cmd_beta"

    def test_the_readings_the_pseudo_code_does_not_state_are_beside_it(self, section):
        """Dies to: the escaped pipe read only one way (DEF-17's body cut at `\\|` reads no
        citation; split on unescaped pipes it is tier 3), or a bare or path-only mention in the
        body silently left out of every reading."""
        beside = section["beside"]
        assert beside["split_on_unescaped_pipes"]["tier3"] == 2
        assert beside["split_on_unescaped_pipes"]["tier3_differ"] == ["DEF-17"]
        assert beside["tier3_if_bare_spelling_counted"] == ["DEF-15"]
        assert beside["tier3_if_a_path_mention_counted"] == ["DEF-15"]


class TestTheDoctorBoundary:
    """cli.py calls doctor back twice (through its module alias and a lazy import); doctor takes
    three of cli's names, one through an alias of cli, and one cli does not define."""

    _CLI = '''\
from espalier import doctor as _doctor

LIMIT = 3


def _probe():
    return _doctor.is_ok()


def _shared():
    return _probe()


def _only_doctor():
    return LIMIT


def _lazy_back():
    from espalier.doctor import verdict
    return verdict()


def cmd_one(args):
    return _shared()


def cmd_two(args):
    return _shared() + _lazy_back()
'''
    _DOCTOR = '''\
def check_a():
    from espalier.cli import _shared, _lazy_back, GONE
    return _shared(), _lazy_back(), GONE


def check_b():
    from espalier import cli as _cli
    return _cli._only_doctor()


def check_c():
    return 0
'''

    @pytest.fixture
    def section(self, repo):
        _add(repo, {"espalier/cli.py": self._CLI, "espalier/doctor.py": self._DOCTOR})
        return _CENSUS.census(repo, _head(repo), ["doctor_boundary"], extra={"concerns": {}})["doctor_boundary"]

    def test_every_name_doctor_takes_is_read_the_alias_loads_included(self, section):
        """Dies to: the names doctor loads through `from espalier import cli as _cli` left out
        (then `_only_doctor` is no import and doctor reaches nothing alone), or a name cli does
        not define counted as one of its functions."""
        names = section["names"]
        assert sorted(names["per_name"]) == ["GONE", "_lazy_back", "_only_doctor", "_shared"]
        assert (names["functions"], names["constants"], names["not_in_cli"]) == (3, 0, ["GONE"])
        assert names["per_name"]["_shared"]["reached_by"] == ["cmd_one", "cmd_two"]
        assert section["doctor_alone"] == ["_only_doctor"]
        assert section["back_edges_left_if_doctor_alone_moved"] == 2
        assert (section["import_statements"], section["doctor_functions"]) == (2, ["check_a", "check_b"])

    def test_the_closure_is_sized_and_its_calls_back_into_doctor_named(self, section):
        """Dies to: the call-back edges read through the module alias alone (the lazy
        `from espalier.doctor import verdict` in `_lazy_back` missed) or through lazy imports
        alone (`_doctor.is_ok` in `_probe` missed), or the closure read over the names themselves
        with nothing they call (`_probe` and `LIMIT` left out)."""
        assert section["calls_back_into_doctor"] == {"_lazy_back": ["verdict"], "_probe": ["is_ok"]}
        assert section["call_back_edges"] == 2
        closure = section["closure"]
        assert (closure["definitions"], closure["functions"], closure["names"], closure["function_lines"]) == (5, 4, 1, 9)
        assert closure["reached_by_no_command"] == ["LIMIT", "_only_doctor"]

    def test_a_pin_without_doctor_names_the_section_unread(self, repo):
        """Dies to: a pin with no doctor.py read as a doctor that imports nothing (a zero)."""
        out = _CENSUS.census(repo, _head(repo), ["doctor_boundary"])
        assert out["doctor_boundary"] is None
        assert "espalier/doctor.py is not in" in out["unread"]["doctor_boundary"]


class TestAnUnreadSectionIsNamedNeverZero:
    def test_a_section_with_no_reader_is_none_and_named(self, repo, monkeypatch):
        """Dies to: a section the census cannot read returned as an empty dict or a zero, which
        reads as clean."""
        monkeypatch.delitem(_CENSUS.SECTION_READERS, "readers")
        out = _CENSUS.census(repo, _head(repo), ["readers"])
        assert out["readers"] is None
        assert "readers" in out["unread"]

    def test_a_pin_without_cli_py_names_the_section_unread(self, repo):
        """Dies to: a missing cli.py at the pin read as a file of zero functions."""
        _git(repo, "rm", "-q", "espalier/cli.py")
        _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "drop")
        _CENSUS.source_at.cache_clear()
        out = _CENSUS.census(repo, _head(repo), ["functions"])
        assert out["functions"] is None
        assert "espalier/cli.py is not in" in out["unread"]["functions"]


# ---------------------------------------------------------------- collision and lane_read: small histories

_UNTIL = "2020-01-02T03:04:05Z"


def _git_try(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=_git_env(), timeout=45)


def _commit_all(repo: pathlib.Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)


def _trunk(repo: pathlib.Path) -> None:
    _git(repo, "branch", "-M", "main")


def _edit(repo: pathlib.Path, old: str, new: str, path: str = "espalier/cli.py") -> None:
    target = repo / path
    text = target.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    target.write_text(text.replace(old, new), encoding="utf-8")


def _lane(repo: pathlib.Path, branch: str, old: str, new: str, *, base: str = "main",
          path: str = "espalier/cli.py") -> str:
    """A branch off `base` with one commit editing `old` to `new`; its head."""
    _git(repo, "checkout", "-q", "-b", branch, base)
    _edit(repo, old, new, path)
    _commit_all(repo, f"edit on {branch}")
    return _head(repo)


def _land(repo: pathlib.Path, number: int, branch: str) -> None:
    """The pull request's merge on main, as GitHub writes it."""
    _git(repo, "checkout", "-q", "main")
    _git(repo, "-c", "commit.gpgsign=false", "merge", "-q", "--no-ff", "-m",
         f"Merge pull request #{number} from owner/{branch}", branch)


def _ctx(repo: pathlib.Path, **extra) -> dict:
    _CENSUS.source_at.cache_clear()
    return {"root": repo, "pin": {**_CENSUS.resolve_pin(repo, _head(repo)), "mail_refs": {}},
            "modules": (_CENSUS.CLI,), **extra}


def _meta(created: str, merged: str) -> dict:
    return {"created": created, "merged": merged}


class TestTheReplayReadsAConflictOnTheCliModule:
    def test_a_conflicting_catch_up_is_listed_and_clean_merges_are_not(self, repo):
        """Three merges, none a pull request's: `main` into lane/x with the same line edited on both
        sides (resolved in the merge), `main` into lane/y (a README only) and lane/y into lane/x.
        Dies to: `replay_merges` reading rc 1 from `git merge-tree` as clean (then the conflict
        on espalier/cli.py is lost and the count reads 0), or a clean merge listed as a conflict."""
        _trunk(repo)
        base = _head(repo)
        _git(repo, "checkout", "-q", "-b", "lane/y", base)
        (repo / "README.md").write_text("readme\n", encoding="utf-8")
        _commit_all(repo, "readme")
        _git(repo, "checkout", "-q", "-b", "lane/x", base)
        _edit(repo, "    return 1\n", "    return 2\n")
        _commit_all(repo, "lane edit")
        _git(repo, "checkout", "-q", "main")
        _edit(repo, "    return 1\n", "    return 3\n")
        _commit_all(repo, "main edit")
        _git(repo, "checkout", "-q", "lane/y")
        _git(repo, "-c", "commit.gpgsign=false", "merge", "-q", "-m", "Merge branch 'main' into lane/y", "main")
        _git(repo, "checkout", "-q", "lane/x")
        assert _git_try(repo, "-c", "commit.gpgsign=false", "merge", "-m",
                        "Merge branch 'main' into lane/x", "main").returncode == 1
        (repo / "espalier" / "cli.py").write_text(_CLI_FIXTURE.replace("    return 1\n", "    return 4\n"),
                                                  encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "--no-edit")
        conflicted = _head(repo)
        _git(repo, "-c", "commit.gpgsign=false", "merge", "-q", "-m", "Merge branch 'lane/y' into lane/x", "lane/y")
        out = _CENSUS.conflicts(_ctx(repo))
        side = out["lane_side"]
        assert side["merges"] == 3
        for arm in ("drivers_on", "drivers_off"):
            assert side[arm]["conflicted_any_file"] == 1
            assert [(r["oid"], r["paths"]) for r in side[arm]["on_cli_modules"]] == [
                (conflicted, ["espalier/cli.py"])]
            assert side[arm]["on_cli_modules"][0]["date"] == _UNTIL
        assert out["catch_ups"]["prs"] == 0


class TestConcurrentPairsAreGradedBySymbol:
    @pytest.fixture
    def pairs(self, repo):
        """#1 and #2 (concurrent) change two different functions; #3 and #4 (concurrent, later)
        change the same one, on lines apart; #5 lands on top of them and changes it too, but after
        all of them merged."""
        _trunk(repo)
        base = _head(repo)
        _lane(repo, "lane/p1", "    return 1\n", "    return 2\n", base=base)
        _land(repo, 1, "lane/p1")
        _lane(repo, "lane/p2", "    return _LATCH\n", "    return not _LATCH\n", base=base)
        _land(repo, 2, "lane/p2")
        _lane(repo, "lane/p3", "    _setter()\n", "    _setter()  # a\n", base=base)
        _land(repo, 3, "lane/p3")
        _lane(repo, "lane/p4", "    return _helper() + len(", "    return _helper() + 2 + len(", base=base)
        _land(repo, 4, "lane/p4")
        _lane(repo, "lane/p5", '    _MEMO["k"] = 1\n', '    _MEMO["k"] = 2\n')
        _land(repo, 5, "lane/p5")
        meta = {1: _meta("2020-01-01T00:00:00Z", "2020-01-01T10:00:00Z"),
                2: _meta("2020-01-01T01:00:00Z", "2020-01-01T09:00:00Z"),
                3: _meta("2020-01-01T12:00:00Z", "2020-01-01T20:00:00Z"),
                4: _meta("2020-01-01T13:00:00Z", "2020-01-01T21:00:00Z"),
                5: _meta("2020-01-02T00:00:00Z", "2020-01-02T01:00:00Z")}
        return _CENSUS.concurrent_pairs(_ctx(repo, _pr_meta=meta))

    def test_only_the_pair_on_one_function_is_graded(self, pairs):
        """Dies to: the pairs counted over shared paths alone, the symbol verdicts dropped (both
        pairs share espalier/cli.py, so two read as graded where one function is shared), or a
        pair on different functions read as a shared symbol."""
        assert pairs["prs"] == 5
        assert pairs["concurrent_pairs"] == 2
        assert pairs["by_verdict"]["different functions"] == 1
        assert pairs["by_verdict"]["shared symbol"] == 1
        assert pairs["graded_count"] == 1
        assert [(p["a"], p["b"], p["verdict"]) for p in pairs["pairs"]] == [
            (1, 2, "different functions"), (3, 4, "shared symbol")]
        assert pairs["pairs"][1]["shared"] == ["espalier/cli.py::cmd_alpha"]

    def test_a_pair_that_never_overlapped_in_time_is_not_counted(self, pairs):
        """Dies to: every pair of CLI-module lanes counted, concurrent or not: #5 changes the
        same function as #3 and #4 but opened after they merged, so it joins no pair."""
        assert all(5 not in (p["a"], p["b"]) for p in pairs["pairs"])

    def test_a_lane_with_no_open_time_is_named_not_paired(self, repo):
        """Dies to: a pull request missing from the opened-at list paired on a default stamp, or
        dropped without a word."""
        _trunk(repo)
        _lane(repo, "lane/p1", "    return 1\n", "    return 2\n")
        _land(repo, 1, "lane/p1")
        out = _CENSUS.concurrent_pairs(_ctx(repo, _pr_meta={}))
        assert out["no_created_at"] == [1]
        assert out["concurrent_pairs"] == 0


class TestACatchUpCarriesACliChangeOrNot:
    def test_only_a_catch_up_that_brings_a_cli_module_change_is_carrying(self, repo):
        """Dies to: every catch-up in the window counted as carrying (the README-only one would
        make it 2), or the diff read against the wrong parent (the lane's own change, not what
        main brought)."""
        _trunk(repo)
        base = _head(repo)
        _git(repo, "checkout", "-q", "-b", "lane/a", base)
        (repo / "a.txt").write_text("a\n", encoding="utf-8")
        _commit_all(repo, "lane a")
        _git(repo, "checkout", "-q", "main")
        _edit(repo, "    return 1\n", "    return 2\n")
        _commit_all(repo, "main brings a cli change")
        _git(repo, "checkout", "-q", "lane/a")
        _git(repo, "-c", "commit.gpgsign=false", "merge", "-q", "-m", "Merge branch 'main' into lane/a", "main")
        _git(repo, "checkout", "-q", "-b", "lane/b", "main")
        (repo / "b.txt").write_text("b\n", encoding="utf-8")
        _commit_all(repo, "lane b")
        _git(repo, "checkout", "-q", "main")
        (repo / "README.md").write_text("readme\n", encoding="utf-8")
        _commit_all(repo, "main brings a readme")
        _git(repo, "checkout", "-q", "lane/b")
        _git(repo, "-c", "commit.gpgsign=false", "merge", "-q", "-m", "Merge branch 'main' into lane/b", "main")
        _git(repo, "-c", "commit.gpgsign=false", "merge", "-q", "-m", "Merge branch 'lane/a' into lane/b", "lane/a")
        out = _CENSUS.catch_ups_carrying(_ctx(repo))
        assert out == {"graded": False, "catch_ups_in_window": 2, "carrying_a_cli_module": 1}


class TestTheHolds:
    _MESSAGES = [
        {"id": "m1", "at": "2020-01-01T03:04:05Z", "type": "assign",
         "text": "Do the cli.py job. Waits for: nothing.", "re": {"paths": ["espalier/cli.py"]}},
        {"id": "m2", "at": "2020-01-01T04:00:00Z", "type": "assign",
         "text": "Lane one first; the other waits for it to merge.", "re": {"paths": ["espalier/cli.py"]}},
        {"id": "m3", "at": "2020-01-01T05:00:00Z", "type": "note",
         "text": "Hold it back until cli.py lands.", "re": {}},
        {"id": "m4", "at": "2020-01-01T06:00:00Z", "type": "note",
         "text": "Waits for the pack to merge.", "re": {"paths": ["docs/x.md"]}},
    ]

    @pytest.fixture
    def ctx(self, repo):
        (repo / "espalier.toml").write_text('dispatcher = "air"\n', encoding="utf-8")
        _commit_all(repo, "toml")
        return _ctx(repo, _mail_at={"air": self._MESSAGES, "other": [
            {"id": "m5", "at": "2020-01-01T07:00:00Z", "text": "the other waits for it, cli.py", "re": {}}]})

    def test_names_module_takes_a_path_or_a_bare_name_as_a_whole_token(self):
        """Dies to: the left boundary dropped (`test_cli.py` accepted), the right boundary dropped
        (`cli.pyc` accepted), or the bare name refused (a message saying `cli.py` unread)."""
        names = _CENSUS.names_module
        assert names("edits espalier/cli.py now", "espalier/cli.py")
        assert names("edits cli.py now", "espalier/cli.py")
        assert not names("edits test_cli.py now", "espalier/cli.py")
        assert not names("edits cli.pyc now", "espalier/cli.py")

    def test_a_waits_for_nothing_line_is_no_hold_and_a_real_wait_is(self, ctx):
        """Dies to: `Waits for: nothing` left in the text (m1 declared, the 'lower bound' inflated),
        the declared path ignored (m2 only text-named), or a message from a seat that is not the
        dispatcher read (m5)."""
        out = _CENSUS.holds(ctx)
        assert out["dispatcher"] == "air"
        assert out["declared"] == ["m2"]
        assert out["named_in_text"] == ["m3"]
        assert out["messages"] == 4

    def test_the_record_starts_at_the_first_message(self, ctx):
        """Dies to: the record's length read from the first message of any seat, or from the clock
        (the fixture pin is in 2020)."""
        out = _CENSUS.holds(ctx)
        assert out["record_from"] == "2020-01-01T03:04:05Z"
        assert out["record_days"] == 1.0

    def test_no_dispatcher_at_the_pin_is_unread_not_empty(self, repo):
        """Dies to: a pin with no espalier.toml reading as a dispatcher with no holds (a zero)."""
        with pytest.raises(_CENSUS.Unread):
            _CENSUS.holds(_ctx(repo, _mail_at={}))


class TestTheClaimOverlap:
    @staticmethod
    def _claim(mid, who, at, lane, paths):
        return {"id": mid, "type": "claim", "from": who, "at": at, "re": {"lane": lane, "paths": paths}}

    @staticmethod
    def _release(mid, who, at, lane):
        return {"id": mid, "type": "release", "from": who, "at": at, "re": {"lane": lane}}

    @pytest.fixture
    def out(self, repo):
        """Three merged CLI lanes. lane/l (seat A, 00:00 to 06:00): seat B's claim on cli.py
        (03:00 to 05:00) falls inside it, seat C's (08:00 to 09:00) after it, seat D's overlaps
        in time but names docs. lane/q (seat E, 20:00 to 22:00): nothing of another seat's, but
        E's own second claim on lane/z names cli.py inside it. lane/n: no claim at all."""
        _trunk(repo)
        for number, branch, old, new in (
                (1, "lane/l", "    return 1\n", "    return 2\n"),
                (2, "lane/q", "    return _LATCH\n", "    return not _LATCH\n"),
                (3, "lane/n", "    _LATCH = True\n", "    _LATCH = False\n")):
            _lane(repo, branch, old, new, base="main")
            _land(repo, number, branch)
        cli = ["espalier/cli.py"]
        d = "2020-01-01T"
        mail = {
            "seatA": [self._claim("a1", "seatA", d + "00:00:00Z", "lane/l", cli),
                      self._release("a2", "seatA", d + "06:00:00Z", "lane/l")],
            "seatB": [self._claim("b1", "seatB", d + "03:00:00Z", "lane/m", cli),
                      self._release("b2", "seatB", d + "05:00:00Z", "lane/m")],
            "seatC": [self._claim("c1", "seatC", d + "08:00:00Z", "lane/c", cli),
                      self._release("c2", "seatC", d + "09:00:00Z", "lane/c")],
            "seatD": [self._claim("d1", "seatD", d + "02:00:00Z", "lane/d", ["docs/x.md"]),
                      self._release("d2", "seatD", d + "04:00:00Z", "lane/d")],
            "seatE": [self._claim("e1", "seatE", d + "20:00:00Z", "lane/q", cli),
                      self._claim("e2", "seatE", d + "21:00:00Z", "lane/z", cli),
                      self._release("e3", "seatE", d + "22:00:00Z", "lane/q"),
                      self._release("e4", "seatE", d + "22:30:00Z", "lane/z")]}
        return _CENSUS.claim_overlaps(_ctx(repo, _mail_at=mail))

    def test_a_lane_overlaps_another_seat_s_claim_on_the_module_in_time(self, out):
        """Dies to: the interval test turned around (`start <= end` read as `>=`: B's window would
        fall outside A's, C's inside), a claim on another path counted (D), or a window ended at
        the wrong release."""
        assert out["lanes"] == 3
        assert out["with_claim_window"] == 2
        assert out["overlapping"] == 1
        assert out["share_graded"] == 0.5
        assert out["share_over_all_lanes"] == round(1 / 3, 3)
        assert out["no_claim"] == [3]
        row = {r["lane"]: r for r in out["rows"]}
        assert row["lane/l"]["overlaps"] == ["seatB:lane/m"]
        assert row["lane/l"]["window"] == ["2020-01-01T00:00:00Z", "2020-01-01T06:00:00Z"]

    def test_the_lane_s_own_seat_is_not_another_seat(self, out):
        """Dies to: the seat's own claim on another lane (E's lane/z, naming cli.py inside lane/q's
        window) counted as another seat's, which makes lane/q overlapping."""
        row = {r["lane"]: r for r in out["rows"]}
        assert row["lane/q"]["overlaps"] == []
        assert row["lane/q"]["seat"] == "seatE"
        assert out["cross_seat_lane_pairs"] == 1
        assert out["strict_overlapping"] == 1


class TestTheLaneRead:
    _SHORT_THEN_LONG = ("def short():\n    a = 1\n    return a\n"
                        "def long():\n" + "".join(f"    v{i} = {i}\n" for i in range(8)) + "    return 0\n"
                        "# ---\n"
                        "def tail():\n    return 0\n")

    @pytest.fixture
    def shaped(self, repo):
        """`short` is lines 1 to 3, `long` 4 to 13 (ten lines) with no gap between, a comment on
        14 and `tail` 15 to 16."""
        _trunk(repo)
        (repo / "espalier" / "cli.py").write_text(self._SHORT_THEN_LONG, encoding="utf-8")
        _commit_all(repo, "shaped")
        _CENSUS.source_at.cache_clear()
        return repo, _head(repo)

    def test_a_hunk_on_the_last_line_of_a_definition_reads_that_definition(self, shaped):
        """Dies to: the hunk placed on the definition after the one it falls in (line + 1): the
        edit on `short`'s last line would read `long`'s 10 lines, not `short`'s 3."""
        repo, base = shaped
        head = _lane(repo, "lane/s", "    return a\n", "    return a + 1\n", base=base)
        out = _CENSUS.lane_read_of(repo, base, head, "espalier/cli.py")
        assert out["lines"] == 3
        assert out["definitions"] == ["short"]

    def test_a_new_function_between_two_definitions_is_placed_on_neither(self, shaped):
        """Dies to: a pure insertion placed on the definition holding the line after it (the
        2,816 against 2,784 of #433): inserting `added` after the comment would read `tail`."""
        repo, base = shaped
        head = _lane(repo, "lane/i", "# ---\n", "# ---\ndef added():\n    return 1\n", base=base)
        assert _CENSUS.hunk_points(_git(repo, "diff", "-U0", base, head)) == [(14, True)]
        out = _CENSUS.lane_read_of(repo, base, head, "espalier/cli.py")
        assert out == {"definitions": [], "lines": 0, "by_definition": {}}

    def test_the_section_sums_each_definition_once_per_lane(self, shaped):
        """Dies to: the lane's lines summed per hunk (two hunks in `long` read 20), or the lane
        left out of the window."""
        repo, base = shaped
        _lane(repo, "lane/s", "    return a\n", "    return a + 1\n", base=base)
        _edit(repo, "    v1 = 1\n", "    v1 = 9\n")
        _edit(repo, "    v5 = 5\n", "    v5 = 9\n")
        _commit_all(repo, "two hunks in long")
        _land(repo, 7, "lane/s")
        out = _CENSUS.section_lane_read(_ctx(repo))
        assert out["lanes"] == 1
        assert out["rows"] == [{"pr": 7, "lines": 13, "definitions": ["long", "short"]}]
        assert out["summed"] == 13
        assert out["top_share"][0] == {"name": "long", "lines": 10, "share": round(10 / 13, 3)}


class TestAWaveIsPaidOnThePrimaryNotOnTheLength:
    def test_a_fall_without_the_primary_paying_does_not_count(self):
        """Dies to: the secondary graded alone: an arbitrary equal split of a function halves
        lane_read (fell True) and a wave that moved nothing on the primary would read paid."""
        out = _CENSUS.wave_payoff(100, 50, primary_paid=False)
        assert out == {"lane_read_fell": True, "primary_paid": False, "paid": False, "lane_read_counts": False}

    def test_a_fall_beside_a_primary_that_paid_counts(self):
        """Dies to: `lane_read_counts` stuck False (a never-paying grade), or `paid` read from the
        length rather than the primary."""
        out = _CENSUS.wave_payoff(100, 50, primary_paid=True)
        assert out["paid"] is True and out["lane_read_counts"] is True

    def test_a_fall_under_the_threshold_is_no_fall(self):
        """Dies to: the threshold read as any fall: 100 to 71 is 29 percent, under the 30 the pack
        fixed; 100 to 70 is on it."""
        assert _CENSUS.wave_payoff(100, 71, primary_paid=True)["lane_read_fell"] is False
        assert _CENSUS.wave_payoff(100, 70, primary_paid=True)["lane_read_fell"] is True
        assert _CENSUS.wave_payoff(0, 0, primary_paid=True)["lane_read_fell"] is False


# ---------------------------------------------------------------- transcripts (Task 0 Item 3's oracle)

_ROOT = "/work/repo"


def _use(tid: str, name: str, at: str, branch: str, **inp) -> dict:
    return {"type": "assistant", "timestamp": at, "gitBranch": branch, "cwd": _ROOT,
            "message": {"content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def _result(tid: str, text: str = "", meta: dict | None = None) -> dict:
    return {"type": "user", "toolUseResult": meta,
            "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": text}]}}


def _lines(n: int) -> str:
    return "\n".join(f"line {i}" for i in range(n))


_LENGTHS = {"espalier/cli.py": 900, "espalier/doctor.py": 100, "docs/a.md": 50}


def _calls(records: list[dict], roots=(_ROOT,)) -> list[dict]:
    return _CENSUS.calls_of(records, list(roots), "2020-01-02T03:04:05Z", lambda p: _LENGTHS.get(p, 0))


class TestATranscriptCallIsReadByTheRuledRules:
    def test_a_read_with_a_limit_counts_the_lines_it_returned_not_the_file(self):
        """Dies to: a Read call's lines counted from the whole file (900) instead of what its
        `limit` returned (40, the result's `numLines`)."""
        calls = _calls([_use("t1", "Read", "2020-01-01T01:00:00Z", "lane/a",
                             file_path=f"{_ROOT}/espalier/cli.py", offset=100, limit=40),
                        _result("t1", _lines(40), {"file": {"numLines": 40}})])
        assert [c["reads"] for c in calls] == [[("espalier/cli.py", 40)]]

    def test_a_piped_whole_read_counts_what_came_out_not_the_file(self):
        """Dies to: a piped read charged the whole file (900): `cat cli.py | head -50` put 50
        lines in front of the seat."""
        calls = _calls([_use("t1", "Bash", "2020-01-01T01:00:00Z", "lane/a",
                             command="cat espalier/cli.py | head -50"),
                        _result("t1", "", {"stdout": _lines(50)})])
        assert calls[0]["reads"] == [("espalier/cli.py", 50)]

    def test_a_path_in_a_heredoc_or_a_redirect_is_not_a_read(self):
        """Dies to: the here-document left in (its body names cli.py, a mention) or a
        redirection's target read as an operand (`> docs/a.md` is a write), either of which
        counts a read here."""
        calls = _calls([_use("t1", "Bash", "2020-01-01T01:00:00Z", "lane/a",
                             command="cat <<'EOF' > docs/a.md\nsed -n 1,5p espalier/cli.py\nEOF"),
                        _result("t1", "", {"stdout": ""}),
                        _use("t2", "Bash", "2020-01-01T01:01:00Z", "lane/a",
                             command="sed -n 1,5p espalier/doctor.py 2>/dev/null"),
                        _result("t2", "", {"stdout": _lines(5)})])
        assert [c["reads"] for c in calls] == [[("espalier/doctor.py", 5)]]

    def test_a_read_in_a_fork_s_gone_worktree_is_a_read_of_the_repo_path(self):
        """Dies to: a worktree that no longer exists read as a path inside the checkout around it
        (`.claude/worktrees/agent-x/espalier/cli.py`, never the CLI module), which zeroed three
        lanes' subagent reads at P (#357, #429, #512)."""
        calls = _calls([_use("t1", "Read", "2020-01-01T01:00:00Z", "lane/a",
                             file_path=f"{_ROOT}/.claude/worktrees/agent-a1b2/espalier/cli.py"),
                        _result("t1", _lines(12), {"file": {"numLines": 12}})])
        assert calls[0]["reads"] == [("espalier/cli.py", 12)]

    def test_a_scratchpad_copy_maps_only_onto_a_file_at_the_pin(self):
        """Dies to: every path under a scratchpad taken as a tree copy (a note there is no repo
        file), or no copy mapped at all (#530's reads of cli.py were in a scratchpad clone)."""
        calls = _calls([_use("t1", "Read", "2020-01-01T01:00:00Z", "lane/a",
                             file_path="/tmp/s/sess/scratchpad/review-clone/espalier/cli.py"),
                        _result("t1", _lines(7), {"file": {"numLines": 7}}),
                        _use("t2", "Read", "2020-01-01T01:01:00Z", "lane/a",
                             file_path="/tmp/s/sess/scratchpad/notes/plan.md"),
                        _result("t2", _lines(9), {"file": {"numLines": 9}})])
        assert [c["reads"] for c in calls] == [[("espalier/cli.py", 7)]]

    def test_a_call_is_counted_once_and_cut_at_the_pin_by_its_own_stamp(self):
        """Dies to: calls deduped by nothing (a record written twice counts twice) or cut by
        anything but the record's own stamp (a call after the pin counted)."""
        use = _use("t1", "Read", "2020-01-01T01:00:00Z", "lane/a", file_path=f"{_ROOT}/espalier/cli.py")
        late = _use("t2", "Read", "2020-01-03T00:00:00Z", "lane/a", file_path=f"{_ROOT}/espalier/cli.py")
        calls = _calls([use, use, _result("t1", "", {"file": {"numLines": 30}}),
                        late, _result("t2", "", {"file": {"numLines": 500}})])
        assert [(c["id"], c["reads"]) for c in calls] == [("t1", [("espalier/cli.py", 30)])]


class TestTheLaneOfACall:
    """Seat s holds lane/a 00:00 to 02:00 (merged 02:30) and lane/b 02:15 to 05:00; lane/x is
    seat t's."""
    SEATS = {"lane/a": "s", "lane/b": "s", "lane/x": "t"}
    WINDOWS = {"s": [("2020-01-01T00:00:00Z", "2020-01-01T02:00:00Z", "lane/a"),
                     ("2020-01-01T02:15:00Z", "2020-01-01T05:00:00Z", "lane/b")]}
    MERGED = {"lane/a": "2020-01-01T02:30:00Z", "lane/b": "2020-01-01T06:00:00Z", "lane/x": "2020-01-01T03:00:00Z"}

    def _of(self, branch, at):
        return _CENSUS.lane_of("s", branch, f"2020-01-01T{at}:00Z", seats=self.SEATS,
                               windows=self.WINDOWS, merged=self.MERGED)

    def test_a_call_on_the_lane_s_branch_is_that_lane_s_and_never_the_other(self):
        """Dies to: a session attributed to the seat's other lane: on lane/a's branch inside
        lane/b's window, before lane/a merged (its catch-up or its row), the call is lane/a's."""
        assert self._of("lane/a", "01:00") == "lane/a"
        assert self._of("lane/a", "02:20") == "lane/a"

    def test_the_default_branch_falls_back_to_the_one_claim_the_seat_holds(self):
        """Dies to: the claim fallback reading the wrong window (lane/a for a call in lane/b's)
        or picking one of two held claims instead of saying ambiguous."""
        assert self._of("main", "04:00") == "lane/b"
        assert self._of("main", "01:00") == "lane/a"
        assert self._of("main", "05:30") == "unattributed"
        assert _CENSUS.lane_of("s", "HEAD", "2020-01-01T02:20:00Z", seats=self.SEATS,
                               windows={"s": [*self.WINDOWS["s"], ("2020-01-01T02:10:00Z", "2020-01-01T02:40:00Z", "lane/c")]},
                               merged=self.MERGED) == "ambiguous"

    def test_a_merged_lane_s_branch_yields_to_the_one_claim_the_seat_then_holds(self):
        """Dies to: the branch taken on its word after its lane merged: the checkout still on
        lane/a's merged branch while the seat holds lane/b's claim (the work in another clone)
        is lane/b's; with no other claim held it stays lane/a's."""
        assert self._of("lane/a", "03:00") == "lane/b"
        assert self._of("lane/b", "07:00") == "lane/b"

    def test_another_seat_s_lane_is_no_unit_of_this_seat(self):
        """Dies to: a branch of another seat's lane re-placed by this seat's clock."""
        assert self._of("lane/x", "04:00") == "other branch"
        assert self._of("lane/unmerged", "04:00") == "other branch"


class TestItem3IsGradedOnTheCommittedRule:
    def test_unmeasured_when_the_read_cannot_see_the_effect(self):
        """Dies to: "not real" given on a read whose minimum detectable ratio is past 2.0 (the
        zeros of lanes that read nothing make the spread wide), or arms under 8 graded."""
        out = _CENSUS.item3_verdict([0, 0, 5000, 3, 0, 40, 7000, 2, 0], [300, 250, 280, 10, 900, 20, 400, 60])
        assert out["verdict"] == "unmeasured" and out["realised_mdr"] > 2.0
        small = _CENSUS.item3_verdict([10, 11, 12], [10, 11, 12])
        assert small["realised_mdr"] <= 2.0 and small["verdict"] == "unmeasured"

    def test_real_only_when_all_three_hold(self):
        """Dies to: one of (a) 1,500 lines, (b) twice E, (c) p under 0.05 dropped: R twice E and
        significant but under 1,500 is not real."""
        e = [100, 120, 90, 110, 105, 95, 115, 100, 98, 102]
        assert _CENSUS.item3_verdict([1600, 1700, 1650, 1800, 1550, 1900, 1620, 1750, 1680, 1710], e)["verdict"] == "real"
        low = _CENSUS.item3_verdict([600, 700, 650, 800, 550, 900, 620, 750, 680, 710], e)
        assert low["a"] is False and low["b"] is True and low["c"] is True and low["verdict"] == "not real"


class TestTheTranscriptsSection:
    @staticmethod
    def _claim(mid, at, lane):
        return {"id": mid, "type": "claim", "from": "air-work", "at": at,
                "re": {"lane": lane, "paths": ["espalier/cli.py"]}}

    @staticmethod
    def _release(mid, at, lane):
        return {"id": mid, "type": "release", "from": "air-work", "at": at, "re": {"lane": lane}}

    @pytest.fixture
    def section(self, repo, tmp_path):
        """lane/a (#1) changes cli.py: treatment. lane/c (#2) changes docs/x.md: control. The
        seat's transcript reads 40 lines of cli.py on lane/a's branch (a limit of a 900-line
        file), 5 of docs/x.md there, 7 of docs/x.md and 99 of cli.py on main inside lane/c's
        claim, and 500 of cli.py after the pin. The project folder differs in case from the
        checkout's derived name."""
        (repo / "docs").mkdir()
        (repo / "docs" / "x.md").write_text("one\ntwo\n", encoding="utf-8")
        _commit_all(repo, "docs")
        _trunk(repo)
        _lane(repo, "lane/a", "    return 1\n", "    return 2\n")
        _land(repo, 1, "lane/a")
        _lane(repo, "lane/c", "two\n", "three\n", path="docs/x.md")
        _land(repo, 2, "lane/c")
        d = "2020-01-01T"
        mail = {"air-work": [self._claim("m1", d + "00:00:00Z", "lane/a"), self._release("m2", d + "02:00:00Z", "lane/a"),
                             self._claim("m3", d + "03:00:00Z", "lane/c"), self._release("m4", d + "05:00:00Z", "lane/c")]}
        root = str(repo)
        proj = tmp_path / "projects" / "proj-work"
        proj.mkdir(parents=True)

        def use(tid, at, branch, name, **inp):
            return {**_use(tid, name, at, branch, **inp), "cwd": root}
        recs = [use("t1", d + "01:00:00Z", "lane/a", "Read", file_path=f"{root}/espalier/cli.py", limit=40),
                _result("t1", "", {"file": {"numLines": 40}}),
                use("t2", d + "01:10:00Z", "lane/a", "Bash", command="sed -n 1,5p docs/x.md"),
                _result("t2", "", {"stdout": _lines(5)}),
                use("t3", d + "04:00:00Z", "main", "Read", file_path=f"{root}/docs/x.md"),
                _result("t3", "", {"file": {"numLines": 7}}),
                use("t4", d + "04:30:00Z", "main", "Read", file_path=f"{root}/espalier/cli.py"),
                _result("t4", "", {"file": {"numLines": 99}}),
                use("t5", "2020-01-03T00:00:00Z", "lane/a", "Read", file_path=f"{root}/espalier/cli.py"),
                _result("t5", "", {"file": {"numLines": 500}})]
        (proj / "s1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")

        def run():
            ctx = _ctx(repo, _mail_at=mail, projects_dir=str(tmp_path / "projects"),
                       checkouts=[{"path": root, "seat": "air-work", "folder": "Proj-Work"}])
            return _CENSUS.section_transcripts(ctx)
        return run

    def test_each_lane_reads_its_own_calls(self, section):
        """Dies to: a Read counted from the whole file, a call attributed to the seat's other lane
        (t4, on main in lane/c's claim, charged to lane/a), the cut at the pin dropped (t5), or E
        read over every file rather than the lane's edited ones."""
        out = section()
        t, = out["treatment"]
        c, = out["control"]
        assert (t["pr"], t["r"], t["e"], t["total"], t["calls"]) == (1, 40, 40, 45, 2)
        assert (c["pr"], c["r"], c["e"], c["total"], c["calls"]) == (2, 99, 7, 106, 2)
        assert out["calls"]["own"] == 4 and out["calls"]["not_on_a_lane"] == {}
        # the population counts the records stamped at or before the pin: t1 to t4, never t5 (a
        # live session appending after P) nor an unstamped line, so a re-run a day later agrees
        assert out["population"][0]["folder"] == "proj-work" and out["population"][0]["records"] == 4
        assert out["seats"] == ["air", "air-work"] and out["of_seats"] == 4

    def test_two_runs_at_one_pin_read_the_same_section(self, section):
        """Dies to: an unsorted walk or a clock read inside the section: two runs at one pin must
        print the same transcripts section (Pass criteria)."""
        assert json.dumps(section(), sort_keys=True, default=sorted) == json.dumps(section(), sort_keys=True, default=sorted)
