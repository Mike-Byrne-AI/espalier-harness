"""`scripts/cli_cost_census.py`, the cli.py audit's instrument (TP-708a).

Every section earns its red on a frozen fixture: a `git init` tree in
`tmp_path` with a small `espalier/cli.py` committed at a fixed date, so a
reading taken from the working tree or the clock lands somewhere else. Each
test names, in its docstring, the mutation it dies to. The fixture's values and
positions disagree with a wrong reading in both directions: a shadowed local
that must give no edge beside a load that must, and a working-tree edit that
must not be read beside the committed text that must.

This file pins the census's readings because every figure in the audit's
result is one of them: a section that read the working tree, the clock or the
wrong spelling would move a verdict silently, with the operator's call resting
on it."""
# slow-exempt: a few `git init`/`commit` spawns per test in tmp_path, each short; the collision, lane_read and worktree classes
# build small branch histories (about 30 spawns the largest), the slowest test 1.2 s; 328 tests in 53 s serial for the module,
# measured 2026-11-18 on the Air at load 3.7 to 5.1
from __future__ import annotations

import ast
import collections
import copy
import importlib.util
import itertools
import json
import os
import pathlib
import re
import statistics
import subprocess
import symtable
from datetime import datetime, timedelta, timezone

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


def _write(path: pathlib.Path, text: str) -> None:
    """A fixture file's bytes, the same on every platform. ``write_text`` writes each
    ``\\n`` as ``\\r\\n`` on Windows, and ``_git_env`` drops the system config, so no
    ``core.autocrlf`` folds it back and the blob keeps it: a test asking a blob's
    exact text then reds on windows-latest alone."""
    path.write_bytes(text.encode("utf-8"))


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
    _write(root / "espalier" / "cli.py", _CLI_FIXTURE)
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
        _write(path, path.read_text(encoding="utf-8") + "\n\ndef cmd_gamma(args):\n    return 0\n")
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
        _write(path, _CLI_FIXTURE + "\n\ndef cmd_gamma(args):\n    return _reader()\n")
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
        _write(repo / "espalier" / "other.py", self._OTHER)
        (repo / "tests").mkdir()
        _write(repo / "tests" / "test_x.py", self._TEST)
        (repo / "docs").mkdir()
        _write(repo / "docs" / "RUN.md", "python -m espalier.cli init .\n")
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
        _write(repo / "tests" / "test_patching.py", self._TEST)
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
        _write(target, text)
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

    def test_each_symbol_is_tallied_by_the_part_it_is_cited_in(self, section):
        """Dies to: the per-symbol tally read off the path spelling alone (`_reader`, cited only
        bare in a struck row, would vanish), the line form counted under a symbol, or a symbol's
        occurrences filed under its file's part where the sweep skips the line as struck
        (`gone`, in a closed row of a swept doc, read as swept)."""
        per = section["per_symbol"]
        assert per["_helper"] == {"struck/struck_fragments": 2, "unchecked_live/code": 1}
        assert per["_reader"] == {"struck/struck_fragments": 1}
        assert per["gone"] == {"struck/struck_lines_in_swept_docs": 1}
        assert per["main"] == {"swept_live/docs": 2}
        assert per["TABLE"] == {"protected_zone/sources": 1, "protected_zone/vendor_twins": 1, "swept_live/docs": 1}
        assert sum(n for cell in per.values() for n in cell.values()) == sum(
            section["totals"][s]["occurrences"] for s in ("path_symbol", "bare_symbol", "dotted"))

    def test_a_sweep_whose_rule_changed_at_the_pin_reads_its_split_unread(self, repo):
        """Dies to: the sweep's rule taken on trust where its text differs from the one ported
        (a changed `_swept_docs` read as the old one), so a population it no longer reads is
        reported as swept."""
        changed = _SWEEP_COPY.replace('("docs/", "memory/", "changelog.d/")', '("docs/", "memory/", "bench/")')
        _add(repo, {**_CITING, "tests/test_doc_source_citations.py": changed})
        out = _CENSUS.census(repo, _head(repo), ["citations"])["citations"]
        assert out["split"]["swept_live"] is None and out["split"]["unchecked_live"] is None
        assert "tests/test_doc_source_citations.py::_swept_docs" in out["unread"]["swept_live"]
        # A struck row is one the sweep's own line rule skips: with that rule unread, so is what
        # it strikes, and the fragments' citations are unread with the rest of its population.
        assert out["split"]["struck"]["struck_fragments"]["path_symbol"]["occurrences"] == 0
        assert "task-packs/ledger.d/DEF-1.md" in out["split"]["unread"]["unread"]["paths"]
        assert out["split"]["record"]["record_set"]["path_symbol"]["occurrences"] == 1

    def test_a_row_is_struck_by_the_sweep_s_line_rule_never_by_its_fragment_s_id_cell(self, repo):
        """Dies to: a whole fragment filed struck because its line-2 id cell starts `~~`, where
        the sweep strikes line by line and only a backticked `~~` span: `~~DEF-7~~`, no
        backticks, is a row the sweep reads (it goes red after a move), and is live. The
        authoring's file-level read, kept beside, still strikes it whole."""
        _add(repo, {**_CITING, "task-packs/ledger.d/DEF-7.md": "<!-- -->\n| ~~DEF-7~~ | `espalier/cli.py::_helper` | x |\n"})
        out = _CENSUS.census(repo, _head(repo), ["citations"])["citations"]
        live = out["split"]["swept_live"]["live_fragments"]
        assert live["paths"] == ["task-packs/ledger.d/DEF-2.md", "task-packs/ledger.d/DEF-7.md"]
        assert _occ(live)["path_symbol"] == 3
        assert _occ(out["split"]["struck"]["struck_fragments"])["path_symbol"] == 2
        assert out["beside"]["substring_by_part"]["struck/struck_fragments"] == {"occurrences": 3, "files": 2}


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
        assert out["by_row"] == {"live": 2, "struck": 1, "not a row": 0, "no row": 1}
        assert out["live_reading_cli"] == 1

    def test_a_fragment_whose_second_line_is_no_row_is_not_read_as_live(self, repo):
        """Dies to: a probe's fragment whose line 2 is no table row (no cells, so no `~~` to
        find) read as a live row, which counts it among the live rows a move would strike."""
        _add(repo, {**_PROBES, "task-packs/ledger.d/DEF-5.md": "<!-- -->\nno table on this line\n"})
        out = _CENSUS.census(repo, _head(repo), ["probes"], extra={"concerns": {}})["probes"]
        rows = {r["id"]: r for r in out["rows"]}
        assert rows["DEF-5"]["row"] == "not a row"
        assert out["not_a_row"] == ["DEF-5"]
        assert out["by_row"] == {"live": 2, "struck": 1, "not a row": 1, "no row": 0}

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


# ---------------------------------------------------------------- the move cost per unit

#: A cli with two hand layers and one hand concern. `core` is `_core` with what it writes and
#: loads; its latch `_SAID` is read by `_core_reader` too (so a patch of `_SAID` has a loader on
#: each side of the core's members), and `_core_reader` also reads `_ANSWER`, written by
#: `_remember`, so the core's tie-closed set pulls both. `deploy` is `_deploy` and what it calls
#: above the core, its memo `_CACHE` with it. `setup` (init and install-ci) owns `_remember`,
#: whose write of `_ANSWER` crosses out of it, and `deploy`; `cmd_scan` is a concern of its own
#: that no parser wires.
_MOVE_CLI = '''\
import os
from espalier import doctor as _doctor
from espalier._text import plural

_SAID = False
_ANSWER = None
_CACHE = {}
LIMIT = 3


def _core():
    global _SAID
    _SAID = not _SAID
    return LIMIT


def _core_reader():
    return _SAID and _ANSWER


def _remember():
    global _ANSWER
    _ANSWER = 1


def _uses_cache(key):
    _CACHE[key] = plural(1)
    return _core()


class Report:
    pass


def _deploy():
    from espalier import fuse
    from espalier.models import Plan
    return _core() + _uses_cache("k") + fuse.X + _doctor.check() + Plan + Report()


def _shared():
    return _core_reader()


def cmd_init(args):
    _remember()
    return _deploy() + _shared()


def cmd_install_ci(args):
    return _deploy()


def cmd_scan(args):
    from espalier import doctor
    return _shared() + _core() + doctor.X


def build_parser():
    parser = object()
    parser.set_defaults(func=cmd_init)
    parser.set_defaults(func=cmd_install_ci)
    return parser
'''

_MOVE_FILES = {
    "espalier/cli.py": _MOVE_CLI,
    "espalier/fuse.py": '''\
import argparse

from espalier.cli import LIMIT


def run(out):
    from espalier.cli import _core, cmd_init, cmd_install_ci
    ns = argparse.Namespace(repo=out, yes=True)
    cmd_install_ci(out)
    return cmd_init(ns), _core(), LIMIT


def other():
    from espalier.cli import cmd_scan
    return cmd_scan(argparse.Namespace(repo="."))
''',
    "espalier/doctor.py": '''\
def check():
    from espalier.cli import GONE, _shared
    return _shared(), GONE


def verdict():
    from espalier import cli as _cli
    return _cli._remember()
''',
    "scripts/gen.py": "from espalier import cli\n\nROWS = (cli.LIMIT, cli._deploy, cli.plural)\n",
    "tests/test_m.py": '''\
from espalier import cli
from espalier.cli import _core, plural


def test_a(monkeypatch):
    monkeypatch.setattr(cli, "_core", lambda: 0)
    monkeypatch.setattr(cli, "_SAID", True, raising=False)
    monkeypatch.setattr(cli, "plural", str)
    monkeypatch.setattr(cli, "_NEW_FLAG", 1, raising=False)
    monkeypatch.setattr(cli._deploy, "__doc__", "patched through cli")
    cli._ANSWER = 2
    assert cli._deploy() and _core() and plural and cli.__file__
''',
    "pyproject.toml": '[project.scripts]\nespalier = "espalier.cli:main"\n',
    "tests/test_n.py": '''\
from espalier.cli import _core, cmd_scan


def test_b(monkeypatch):
    monkeypatch.setattr("espalier.cli._uses_cache", lambda k: 0)
    monkeypatch.setattr("espalier.cli._core", lambda: 0)
    assert cmd_scan(None) is not None and _core
''',
    "tests/test_r.py": '''\
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = {("espalier/cli.py", "_deploy"): 1, ("espalier/cli.py", "_core"): 2, ("espalier/cli.py", "not_here"): 3}


def test_text_has_no_tabs():
    assert "\\t" not in (ROOT / "espalier" / "cli.py").read_text()


def test_names_a_member():
    src = (ROOT / "espalier" / "cli.py").read_text()
    assert "_remember" in src
''',
    "tests/test_flat.py": 'import glob\nFILES = glob.glob("espalier/*.py")\n',
    "tests/test_doc_source_citations.py": _SWEEP_COPY,
    "espalier/surface_contract.py": _CONTRACT_COPY,
    "task-packs/ledger.d/DEF-1.md": ("<!-- class: §C0 -->\n"
                                     "| `DEF-1` | `espalier/cli.py::_core` | the body cites `cli.py::_remember` |\n"),
    "task-packs/ledger.d/DEF-2.md": "<!-- class: §C0 -->\n| ~~`DEF-2`~~ | `espalier/cli.py::_deploy` | closed |\n",
    "docs/GUIDE.md": ("See `espalier/cli.py::_core`, `espalier.cli.plural`, `espalier/cli.py::gone` and "
                      "espalier/cli.py:12.\n"),
    "docs/session-archive.md": "Found `espalier/cli.py::_uses_cache` then.\n",
    "task-packs/TP-9-plan.md": "Move `espalier/cli.py::cmd_scan`.\n",
    "tools/cc/hook.py": "# reads espalier/cli.py::LIMIT\nX = 1\n",
    "espalier/_vendor/cc/hook.py": "# reads espalier/cli.py::LIMIT\nX = 1\n",
    "task-packs/probes.d/DEF-1.json": json.dumps({
        "id": "DEF-1", "subject": "docs/x.md", "cmd": "python -c 'from espalier import cli; print(cli._core())'"}),
    "task-packs/probes.d/DEF-2.json": json.dumps({
        "id": "DEF-2", "subject": "espalier/cli.py",
        "cmd": "python3 -c \"import ast; t=ast.parse(open('espalier/cli.py').read()); "
               "print(any(getattr(n,'name','')=='_deploy' for n in ast.walk(t)))\""}),
    "task-packs/probes.d/DEF-3.json": json.dumps({"id": "DEF-3", "subject": "espalier/cli.py", "cmd": None}),
    "task-packs/probes.d/DEF-4.json": json.dumps({
        "id": "DEF-4", "subject": "docs/y.md",
        "cmd": "python -c 'from espalier import cli; print(cli.LIMIT, cli.plural, cli._core)'"}),
    "task-packs/probes.d/DEF-5.json": json.dumps({
        "id": "DEF-5", "subject": "docs/z.md", "cmd": "python3 -c \"print(open('espalier/cli.py').read().count('d'))\""}),
}

_MOVE_EXTRA = {
    "layer_seeds": (("core", ("_core",)), ("deploy", ("_deploy",))),
    "concerns": {"setup": ("cmd_init", "cmd_install_ci")},
    "reader_classes": (("tests/test_r.py", "test_text_has_no_tabs", "silent"),
                       ("tests/test_r.py", "test_names_a_member", "silent"),
                       ("tests/test_flat.py", None, "flat-module")),
}

#: Each ingredient's section, and where in it the total the move cost sums against lives.
_TOTAL_AT = {
    "importers_outside": ("importers", ("outside_tests", "distinct_names")),
    "test_imports": ("importers", ("tests", "distinct_names")),
    "patch_sites": ("patches", ("sites",)),
    "patch_targets": ("patches", ("targets",)),
    "patch_raising_false": ("patches", ("raising_false", "_SAID", "raising_false")),
    "symbol_keys": ("readers", ("by_kind", "symbol_key", "sites")),
    "citations": ("citations", ("totals", "path_symbol", "occurrences")),
    "probes": ("probes", ("symbols_named", "pairs")),
    "doctor": ("doctor_boundary", ("names", "count")),
    "lazy_imports": ("functions", ("unresolved", "lazy_imports")),
}


class TestTheMoveCost:
    """Every ingredient's value differs between the units, and between a unit's members and its
    tie-closed set, so a figure read over the wrong set, the whole file, or the wrong side of a
    loader lands on another unit's number."""

    @pytest.fixture
    def moving(self, repo):
        _add(repo, _MOVE_FILES)
        return repo

    @pytest.fixture
    def section(self, moving):
        out = _CENSUS.census(moving, _head(moving), ["move_cost"], extra=dict(_MOVE_EXTRA))
        assert out["unread"] == {}
        units = {(u["unit"], u["set"]): u for u in out["move_cost"]["units"]}
        return out["move_cost"], units

    def test_the_units_are_each_layer_twice_and_each_concern_once(self, section):
        """Dies to: the tie-closed set left unpriced (the core then moves without the reader of
        its latch), the concern priced over its reach instead of what it owns (`_shared` and the
        core would join `setup`), or a single-command concern dropped."""
        _mc, units = section
        assert list(units) == [("core", "members"), ("core", "tie_closed"), ("deploy", "members"),
                               ("deploy", "tie_closed"), ("setup", "owned"), ("cmd_scan", "owned")]
        assert units[("core", "members")]["members"] == ["LIMIT", "_SAID", "_core"]
        assert units[("core", "tie_closed")]["members"] == ["LIMIT", "_ANSWER", "_SAID", "_core", "_core_reader",
                                                            "_remember"]
        assert units[("setup", "owned")]["members"] == ["Report", "_CACHE", "_deploy", "_remember", "_uses_cache",
                                                        "cmd_init", "cmd_install_ci"]
        assert (units[("setup", "owned")]["cluster_source"], units[("cmd_scan", "owned")]["cluster_source"]) == (
            "hand", "command")

    def test_size_counts_every_kind_and_function_lines_only_over_functions(self, section):
        """Dies to: the unit's definitions read as its functions (3, not 7, for setup), or the
        class's and the names' lines counted as function lines."""
        _mc, units = section
        assert units[("core", "tie_closed")]["size"] == {"definitions": 6, "functions": 3, "classes": 0, "names": 3,
                                                         "function_lines": 9}
        assert units[("setup", "owned")]["size"] == {"definitions": 7, "functions": 5, "classes": 1, "names": 1,
                                                     "function_lines": 15}

    def test_the_importers_outside_tests_are_named_by_file_and_by_how(self, section):
        """Dies to: every import read as lazy (fuse's module-level `LIMIT` and scripts/gen.py's
        alias are top-level), the (file, name) pairs read as distinct names (3 against 2), or a
        test file's import counted outside tests."""
        _mc, units = section
        core = units[("core", "members")]["importers_outside"]
        assert core["files"] == {"espalier/fuse.py": {"lazy": ["_core"], "top": ["LIMIT"]},
                                 "scripts/gen.py": {"top": ["LIMIT"]}}
        assert (core["names"], core["pairs"]) == (2, 3)
        tied = units[("core", "tie_closed")]["importers_outside"]
        assert tied["files"]["espalier/doctor.py"] == {"lazy": ["_remember"]}
        assert (tied["names"], tied["pairs"]) == (3, 4)

    def test_a_hand_built_namespace_is_flagged_on_the_unit_that_holds_the_command(self, section):
        """Dies to: the Namespace read only where it is built inline (fuse binds `cmd_init`'s to a
        name first), a call with a plain argument flagged (`cmd_install_ci(out)`), or the flag
        put on every unit rather than the one holding the command."""
        mc, units = section
        assert units[("setup", "owned")]["importers_outside"]["namespace_by_hand"] == [
            {"file": "espalier/fuse.py", "name": "cmd_init", "line": 10, "attributes": ["repo", "yes"]}]
        assert units[("cmd_scan", "owned")]["importers_outside"]["namespace_by_hand"] == [
            {"file": "espalier/fuse.py", "name": "cmd_scan", "line": 15, "attributes": ["repo"]}]
        assert units[("deploy", "members")]["importers_outside"]["namespace_by_hand"] == []
        assert [c["name"] for c in mc["namespace_by_hand"]["espalier/fuse.py"]] == ["cmd_init", "cmd_scan"]

    def test_the_names_tests_import_are_counted_by_name_and_by_file(self, section):
        """Dies to: the test files read as one per name (`_core` is imported by two), or the names
        loaded through a test's alias of cli (`cli._ANSWER`) left out."""
        _mc, units = section
        assert units[("core", "members")]["test_imports"] == {"names": 1, "files": 2, "pairs": 2,
                                                              "stored_only_pairs": 0, "per_name": {"_core": 2}}
        assert units[("core", "tie_closed")]["test_imports"] == {"names": 2, "files": 2, "pairs": 3,
                                                                 "stored_only_pairs": 1,
                                                                 "per_name": {"_ANSWER": 1, "_core": 2}}

    def test_a_patch_target_s_loaders_are_split_by_the_unit(self, section):
        """Dies to: the loaders outside the unit read as every loader (then `_uses_cache`, loaded
        only by `_deploy`, reads as left behind), a target a member loads but the unit does not
        hold (`_core`, `plural` for deploy) left out of the hazard, or a target left behind read
        by one side alone: `_core`, whose loaders all stay in cli, is reached by its patch, and
        `_ANSWER`, whose one loader moves with it, has no loader left behind to keep it green."""
        _mc, units = section
        core = units[("core", "members")]["patches"]
        assert (core["targets"], core["sites"], core["raising_false"], core["files"]) == (2, 3, 1, 2)
        assert core["per_target"]["_core"] == {"sites": 2, "raising_false": 0, "assign": 0, "loaders_inside": [],
                                               "loaders_outside": ["_deploy", "_uses_cache", "cmd_scan"]}
        assert core["per_target"]["_SAID"]["loaders_inside"] == ["_core"]
        assert core["left_behind_loader"] == {"targets": ["_SAID"], "sites": 1}
        tied = units[("core", "tie_closed")]["patches"]
        assert tied["left_behind_loader"] == {"targets": [], "sites": 0}
        assert tied["per_target"]["_SAID"]["loaders_inside"] == ["_core", "_core_reader"]
        assert tied["per_target"]["_ANSWER"]["loaders_inside"] == ["_core_reader"]
        deploy = units[("deploy", "members")]["patches"]
        assert deploy["per_target"]["_uses_cache"]["loaders_outside"] == []
        assert deploy["left_behind_loader"] == {"targets": [], "sites": 0}
        assert deploy["loaded_not_member"] == {"targets": ["_core", "plural"], "sites": 3}

    def test_readers_name_their_keys_and_a_silent_reader_covers_what_it_names(self, section):
        """Dies to: the symbol keys read over the whole file (3, not 1, on each unit), or a silent
        reader that names one definition (`_remember`) read as covering the whole file, so it
        lands on the core it never reads."""
        _mc, units = section
        core = units[("core", "members")]["readers"]
        assert core["symbol_key"] == {"sites": 1, "files": 1, "symbols": ["_core"],
                                      "by_class": {"loud": 1, "silent": 0, "flat-module": 0}}
        assert core["silent"] == [{"path": "tests/test_r.py", "symbol": "test_text_has_no_tabs",
                                   "covers": "whole file"}]
        assert core["flat_module"] == [{"path": "tests/test_flat.py", "symbol": None, "covers": "whole file"}]
        tied = units[("core", "tie_closed")]["readers"]["silent"]
        assert [s["symbol"] for s in tied] == ["test_text_has_no_tabs", "test_names_a_member"]
        assert tied[1]["covers"] == ["_remember"]

    def test_citations_are_split_by_where_they_live(self, section):
        """Dies to: a member's citations filed under the wrong split (the record's `_uses_cache`
        read as swept, a test's dotted string as a doc), or one file counted once per citation."""
        _mc, units = section
        core = units[("core", "members")]["citations"]
        assert core["occurrences"] == 5
        assert core["split"]["swept_live"] == {"live_fragments": {"occurrences": 1, "files": 1},
                                               "docs": {"occurrences": 1, "files": 1}}
        assert core["split"]["unchecked_live"]["code"] == {"occurrences": 1, "files": 1}
        assert core["split"]["protected_zone"] == {"sources": {"occurrences": 1, "files": 1},
                                                   "vendor_twins": {"occurrences": 1, "files": 1}}
        tied = units[("core", "tie_closed")]["citations"]["split"]["swept_live"]
        assert tied["live_fragments"] == {"occurrences": 2, "files": 1}
        deploy = units[("deploy", "members")]["citations"]
        assert deploy["occurrences"] == 3
        assert deploy["split"]["record"]["record_set"]["occurrences"] == 1
        assert deploy["split"]["struck"]["struck_fragments"]["occurrences"] == 1
        assert deploy["split"]["swept_live"]["docs"]["occurrences"] == 0

    def test_probes_are_named_by_the_symbols_they_read(self, section):
        """Dies to: a probe attributed by its subject alone (DEF-3 reads cli.py by subject and
        names nothing), or every probe read against every unit."""
        mc, units = section
        assert units[("core", "members")]["probes"] == {"ids": ["DEF-1", "DEF-4"], "pairs": 3,
                                                        "by_row": {"live": 1, "struck": 0, "not a row": 0, "no row": 1}}
        assert units[("deploy", "members")]["probes"] == {"ids": ["DEF-2"], "pairs": 1,
                                                          "by_row": {"live": 0, "struck": 1, "not a row": 0, "no row": 0}}
        assert units[("cmd_scan", "owned")]["probes"]["ids"] == []
        assert mc["not_attributed"]["probes"] == {"reading_cli_no_symbol": ["DEF-5"], "subject_only": ["DEF-3"]}

    def test_the_probes_section_totals_the_symbol_pairs_the_move_cost_sums(self, moving):
        """Dies to: the total read as the probes that read cli (4), the rows that name a symbol
        (3) or the distinct symbols (4), where the move cost sums (probe, symbol) pairs (5:
        DEF-4 names three, one of them `_core`, which DEF-1 names too)."""
        out = _CENSUS.census(moving, _head(moving), ["probes"], extra=dict(_MOVE_EXTRA))["probes"]
        assert out["symbols_named"] == {"pairs": 5, "distinct": 4, "probes": 3}
        assert out["reading_cli"] == 4

    def test_outbound_edges_name_the_back_edge_and_the_cycles_they_close(self, section):
        """Dies to: the back edges read over the members too (deploy's own `_uses_cache` call
        counted), a top-level import a member loads left out (`_doctor` is deploy's edge into
        doctor), or a cycle through an importer called closed where cli keeps no caller of the
        unit (`cmd_scan`, which no parser wires, imports doctor and doctor takes none of it)."""
        _mc, units = section
        deploy = units[("deploy", "members")]["outbound"]
        assert deploy["lazy"] == {"statements": 2, "by_module": {"espalier.fuse": 1, "espalier.models": 1}}
        assert deploy["top_level_imports_loaded"] == {"espalier._text": ["plural"], "espalier.doctor": ["_doctor"]}
        assert deploy["back_edges"] == {"definitions": 1, "edges": 2, "writes": 0, "names": ["_core"]}
        assert deploy["cli_callers"] == {"definitions": 2, "edges": 2, "members_kept_bound": ["_deploy"]}
        assert deploy["cli_cycle"] is True
        assert [(c["module"], c["via"], c["closes"]) for c in deploy["importer_cycles"]] == [
            ("espalier.doctor", ["top"], True), ("espalier.fuse", ["lazy"], True)]
        setup = units[("setup", "owned")]["outbound"]
        assert setup["back_edges"] == {"definitions": 3, "edges": 4, "writes": 1, "names": ["_ANSWER", "_core", "_shared"]}
        assert setup["importer_cycles"][1]["takes_members"] == ["cmd_init", "cmd_install_ci"]
        scan = units[("cmd_scan", "owned")]["outbound"]
        assert scan["cli_callers"] == {"definitions": 0, "edges": 0, "members_kept_bound": []}
        assert scan["cli_cycle"] is False
        assert scan["importer_cycles"] == [{"module": "espalier.doctor", "via": ["lazy"], "takes_members": [],
                                            "takes_other_names": 3, "closes": False}]
        core = units[("core", "members")]["outbound"]
        assert core["back_edges"]["edges"] == 0
        assert core["cli_callers"] == {"definitions": 4, "edges": 4, "members_kept_bound": ["_SAID", "_core"]}

    def test_the_doctor_names_are_the_members_doctor_takes(self, section):
        """Dies to: every doctor name read against every unit, or a name doctor takes through
        its alias of cli (`_cli._remember`) left out."""
        _mc, units = section
        assert units[("core", "members")]["doctor"] == {"names": [], "count": 0}
        assert units[("core", "tie_closed")]["doctor"] == {"names": ["_remember"], "count": 1}
        assert units[("setup", "owned")]["doctor"] == {"names": ["_remember"], "count": 1}

    def test_with_re_exports_the_stale_sites_and_the_split_latches_are_named(self, section):
        """Dies to: a patch read as stale where every loader of its target stays in cli (the
        core's `_core`, loaded only outside it), a `None` latch left out of the split (`_ANSWER`),
        a memo dict read as one that splits, or the cycle read as needing a caller left in cli
        (with re-exports cli imports the new module itself, so a back edge alone closes one)."""
        _mc, units = section
        core = units[("core", "members")]["with_reexports"]
        assert core["stale_patch_sites"] == {"targets": ["_SAID"], "sites": 1, "of_which_loaders_on_both_sides": 1}
        assert core["latches_split"] == [{"latch": "_SAID", "value": "bool", "users_outside": ["_core_reader"]}]
        assert (core["loud_readers"], core["cli_cycle"]) == (1, False)
        tied = units[("core", "tie_closed")]["with_reexports"]
        assert tied["stale_patch_sites"] == {"targets": ["_ANSWER", "_SAID"], "sites": 2,
                                             "of_which_loaders_on_both_sides": 0}
        assert [r["latch"] for r in tied["latches_split"]] == ["_ANSWER", "_SAID"]
        deploy = units[("deploy", "members")]["with_reexports"]
        assert deploy["stale_patch_sites"] == {"targets": ["_uses_cache"], "sites": 1,
                                               "of_which_loaders_on_both_sides": 0}
        assert deploy["stale_in_both"] == {"targets": ["_core", "plural"], "sites": 3}
        assert (deploy["latches_split"], deploy["memos_shared"]) == ([], ["_CACHE"])
        scan = units[("cmd_scan", "owned")]
        assert (scan["with_reexports"]["cli_cycle"], scan["outbound"]["cli_cycle"]) == (True, False)

    def test_a_latch_left_in_cli_that_a_member_writes_is_named_in_both_branches(self, section):
        """Dies to: the split latches read only among the members, so `setup`, which moves
        `_remember` and leaves `_ANSWER` in cli, reads as splitting nothing while its moved
        `global _ANSWER` write would rebind the new module's copy; or the latch read as crossing
        where no member touches it (deploy)."""
        _mc, units = section
        setup = units[("setup", "owned")]
        assert setup["latches_across"] == [{"latch": "_ANSWER", "value": "None", "members_writing": ["_remember"],
                                            "members_reading": []}]
        assert setup["with_reexports"]["latches_across"] == setup["without_reexports"]["latches_across"] == ["_ANSWER"]
        assert units[("deploy", "members")]["latches_across"] == []
        assert units[("core", "members")]["latches_across"] == []

    def test_a_unit_that_imports_cli_back_is_named_for_the_module_run(self, section):
        """Dies to: the `-m` second copy left unread, or read as holding state for a unit that
        never imports cli (the core has no back edge)."""
        _mc, units = section
        assert units[("setup", "owned")]["module_run"] == {"imports_cli": True, "state_in_a_second_copy": ["_ANSWER"]}
        assert units[("deploy", "members")]["module_run"] == {"imports_cli": True, "state_in_a_second_copy": []}
        assert units[("core", "members")]["module_run"] == {"imports_cli": False, "state_in_a_second_copy": []}

    def test_without_re_exports_the_loud_sites_leave_out_the_silent_creates(self, section):
        """Dies to: a `raising=False` patch or an assignment counted as failing loudly (each
        creates the attribute and reaches nothing), the assignment counted again as a loud test
        import (`cli._ANSWER = 2` only stores), or the loud total summed over the wrong parts."""
        _mc, units = section
        tied = units[("core", "tie_closed")]["without_reexports"]
        assert tied["test_imports"] == {"names": 2, "files": 2, "pairs": 3, "stored_only_pairs": 1, "loud_pairs": 2}
        assert tied["patches"] == {"loud_sites": 2, "silent_creates": 2}
        assert tied["outside_importers"] == {"names": 3, "pairs": 4, "files": 3}
        assert (tied["loud_readers"], tied["loud_sites"]) == (1, 9)
        assert units[("setup", "owned")]["without_reexports"]["loud_sites"] == 7

    def test_without_re_exports_the_names_cli_still_loads_are_priced_both_ways(self, section):
        """Dies to: the loud sites read as loud whatever spelling cli keeps for the names it still
        calls: where cli from-imports them, `cli._core` stays bound and its test imports, patches
        and importers stop failing; or the names read off the members a test touches rather than
        those a definition left in cli loads (`setup` keeps `cmd_init` and `cmd_install_ci`
        bound only for the parser)."""
        _mc, units = section
        tied = units[("core", "tie_closed")]["without_reexports"]["if_cli_from_imports_what_it_still_loads"]
        assert tied == {"names": ["_core", "_core_reader", "_remember"], "test_import_pairs": 2, "patch_sites": 2,
                        "outside_importer_pairs": 2, "loud_sites": 3}
        setup = units[("setup", "owned")]["without_reexports"]
        assert setup["if_cli_from_imports_what_it_still_loads"] == {
            "names": ["cmd_init", "cmd_install_ci"], "test_import_pairs": 0, "patch_sites": 0,
            "outside_importer_pairs": 2, "loud_sites": 5}
        assert setup["stale_in_both"] == units[("setup", "owned")]["with_reexports"]["stale_in_both"]

    def test_what_no_unit_is_charged_is_named_beside_the_units(self, section):
        """Dies to: the sites the move cost attributes to no unit dropped from its output (the
        path joins of test_r.py, the line form in docs/GUIDE.md, the patch of `_deploy.__doc__`
        through cli), so a reader takes the per-unit figures for the whole of what reads cli."""
        mc, _units = section
        na = mc["not_attributed"]
        assert na["reader_sites"] == {"path_literal": 0, "path_join": 2}
        assert na["citation_line_form"] == 1
        assert na["patches_through_cli"] == {"sites": 1, "targets": ["_deploy.__doc__"],
                                             "first_part_defined_in_cli": ["_deploy"]}

    def test_in_split_sums_only_the_parts_that_were_read(self, moving):
        """Dies to: `in_split` summing the `unread` part too, which MOVE_RULES says it leaves out:
        under a sweep whose rule differs at the pin, every unit's `in_split` then equals its whole
        `occurrences`, as if the swept and unchecked splits had been read; or the partition
        checked over split cells it knows are partial (it is named unchecked instead)."""
        changed = _SWEEP_COPY.replace('("docs/", "memory/", "changelog.d/")', '("docs/", "memory/", "bench/")')
        _add(moving, {"tests/test_doc_source_citations.py": changed})
        out = _CENSUS.census(moving, _head(moving), ["move_cost"], extra=dict(_MOVE_EXTRA))
        mc = out["move_cost"]
        core = next(u for u in mc["units"] if (u["unit"], u["set"]) == ("core", "members"))["citations"]
        unread_part = core["split"]["unread"]["unread"]["occurrences"]
        assert unread_part > 0
        assert core["in_split"] == core["occurrences"] - unread_part
        assert core["split"]["swept_live"] is None
        assert "citations" in mc["partition"]["unchecked"]
        assert "the sweep's rule differs" in out["unread"]["move_cost.citations.swept_live"]

    def test_the_concern_units_partition_the_file_and_their_figures_sum(self, section):
        """Dies to: a concern unit priced over a set other than what it owns, or a per-unit
        figure aggregated over the wrong set, which the whole-file sum cannot see."""
        mc, _units = section
        part = mc["partition"]
        assert (part["concern_units"], part["owned"], part["rest"], part["unchecked"]) == (2, 8, 7, {})
        assert part["ingredients"]["patch_sites"] == {"concern_units": 1, "rest": 4, "defined": 5}
        assert part["ingredients"]["citations"] == {"concern_units": 5, "rest": 5, "defined": 10}

    def test_a_split_part_the_units_do_not_read_is_refused(self, moving, monkeypatch):
        """Dies to: the partition not asserted, so a citation part missing from the split the
        units are priced from (here `unchecked_live/code`, which holds test_n's dotted
        `espalier.cli._uses_cache`) leaves every unit short with the whole-file sum still whole."""
        real = _CENSUS.SECTION_READERS["citations"]

        def dropped(ctx):
            out = copy.deepcopy(real(ctx))
            del out["split"]["unchecked_live"]["code"]
            return out

        monkeypatch.setitem(_CENSUS.SECTION_READERS, "citations", dropped)
        with pytest.raises(AssertionError, match="move_cost: citations's concern units read"):
            _CENSUS.census(moving, _head(moving), ["move_cost"], extra=dict(_MOVE_EXTRA))

    def test_each_ingredient_sums_over_the_file_with_cli_s_imports_apart(self, section):
        """Dies to: a name cli imports (`plural`) counted with the names it does not bind at all
        (`_NEW_FLAG`, `GONE`, `__file__`), or with its definitions."""
        mc, _units = section
        sums = mc["sums"]
        assert {k: (v["defined"], v["imported_into_cli"], v["not_bound_in_cli"], v["section_total"])
                for k, v in sums.items()} == {
            "importers_outside": (8, 1, 1, 10), "test_imports": (4, 1, 1, 6), "patch_sites": (5, 1, 1, 7),
            "patch_targets": (4, 1, 1, 6), "patch_raising_false": (1, 0, 1, 2), "symbol_keys": (2, 0, 1, 3),
            "citations": (10, 1, 1, 12), "probes": (4, 1, 0, 5), "doctor": (2, 0, 1, 3), "lazy_imports": (3, 0, 0, 3)}
        assert sums["patch_sites"]["apart"] == {"imported_into_cli": ["plural"], "not_bound_in_cli": ["_NEW_FLAG"]}
        assert sums["test_imports"]["apart"]["not_bound_in_cli"] == ["__file__"]

    @pytest.mark.parametrize("ingredient", sorted(_TOTAL_AT))
    def test_a_section_total_the_tallies_do_not_reach_is_refused(self, moving, monkeypatch, ingredient):
        """Dies to: an ingredient's sum not asserted, so a tally that misses part of its section's
        total (one site, one name) is priced as if it were whole."""
        section, path = _TOTAL_AT[ingredient]
        real = _CENSUS.SECTION_READERS[section]

        def bumped(ctx):
            out = copy.deepcopy(real(ctx))
            cell = out
            for key in path[:-1]:
                cell = cell[key]
            cell[path[-1]] += 1
            return out

        monkeypatch.setitem(_CENSUS.SECTION_READERS, section, bumped)
        with pytest.raises(AssertionError, match=f"move_cost: {ingredient} reads"):
            _CENSUS.census(moving, _head(moving), ["move_cost"], extra=dict(_MOVE_EXTRA))

    def test_a_section_s_own_split_the_apart_parts_do_not_match_is_refused(self, moving, monkeypatch):
        """Dies to: the apart parts never checked against the split the section states itself
        (the patches section's imported-into-cli sites), so a name read as defined in one and
        imported in the other passes."""
        real = _CENSUS.SECTION_READERS["patches"]

        def moved(ctx):
            out = copy.deepcopy(real(ctx))
            out["imported_into_cli"]["sites"] += 1
            return out

        monkeypatch.setitem(_CENSUS.SECTION_READERS, "patches", moved)
        with pytest.raises(AssertionError, match="move_cost: patch_sites's apart parts"):
            _CENSUS.census(moving, _head(moving), ["move_cost"], extra=dict(_MOVE_EXTRA))

    def test_two_concern_units_holding_one_definition_are_refused(self, moving):
        """Dies to: the concern units never checked for overlap, so a definition priced in two
        units (here `_deploy`, added to `cmd_scan`'s as well as `setup`'s) is paid for twice and
        the partition's sum reads over a file that is larger than it is."""
        clusters = _CENSUS.census(moving, _head(moving), ["clusters"], extra=dict(_MOVE_EXTRA))["clusters"]
        doubled = copy.deepcopy(clusters)
        doubled["concerns"]["per_root"]["cmd_scan"]["members"].append("_deploy")
        with pytest.raises(AssertionError, match="move_cost: _deploy is in two concern units"):
            _CENSUS.census(moving, _head(moving), ["move_cost"], extra={**_MOVE_EXTRA, "_clusters": doubled})

    def test_an_ingredient_whose_section_is_unread_is_named_never_zero(self, repo):
        """Dies to: a unit priced at zero citations or zero doctor names on a pin where the sweep
        or doctor.py cannot be read, which reads as a free move."""
        out = _CENSUS.census(repo, _head(repo), ["move_cost"],
                             extra={"layer_seeds": (("low", ("_reader",)),), "concerns": {}})
        assert "espalier/doctor.py is not in" in out["unread"]["move_cost.doctor"]
        assert "test_doc_source_citations.py is not in" in out["unread"]["move_cost.citations"]
        unit = out["move_cost"]["units"][0]
        assert (unit["doctor"], unit["citations"]) == (None, None)
        assert "doctor" not in out["move_cost"]["sums"] and "citations" not in out["move_cost"]["sums"]
        assert unit["patches"] is not None

    def test_a_pin_without_cli_py_names_the_section_unread(self, repo):
        """Dies to: a pin with no cli.py priced as a file of no units."""
        _git(repo, "rm", "-q", "espalier/cli.py")
        _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "drop")
        _CENSUS.source_at.cache_clear()
        out = _CENSUS.census(repo, _head(repo), ["move_cost"])
        assert out["move_cost"] is None
        assert "espalier/cli.py is not in" in out["unread"]["move_cost"]


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
    _write(target, text.replace(old, new))


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
        lane/y then lands as #5, the pin's `.gitattributes` gives cli.py the union driver, and
        lane/x lands as #7. Dies to: `replay_merges` reading rc 1 from `git merge-tree` as clean
        (then the conflict on espalier/cli.py is lost and the count reads 0), or a clean merge
        listed as a conflict; the drivers-on arm replayed without the pin's attributes (it then
        reads the conflict the union driver merges clean, as the drivers-off arm does); or the
        catch-ups read off anything but each pull request's own commits (#7 carries the one that
        conflicts, #5 a clean one, and the lowest number is 5)."""
        _trunk(repo)
        base = _head(repo)
        _git(repo, "checkout", "-q", "-b", "lane/y", base)
        _write(repo / "README.md", "readme\n")
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
        _write(repo / "espalier" / "cli.py", _CLI_FIXTURE.replace("    return 1\n", "    return 4\n"))
        _git(repo, "add", "-A")
        _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "--no-edit")
        conflicted = _head(repo)
        _git(repo, "-c", "commit.gpgsign=false", "merge", "-q", "-m", "Merge branch 'lane/y' into lane/x", "lane/y")
        _land(repo, 5, "lane/y")
        _write(repo / ".gitattributes", "espalier/cli.py merge=union\n")
        _commit_all(repo, "the union driver for cli.py")
        _land(repo, 7, "lane/x")
        out = _CENSUS.conflicts(_ctx(repo))
        side = out["lane_side"]
        assert side["merges"] == 3
        assert side["drivers_on"] == {"conflicted_any_file": 0, "on_cli_modules": []}
        assert side["drivers_off"]["conflicted_any_file"] == 1
        assert [(r["oid"], r["paths"], r["date"]) for r in side["drivers_off"]["on_cli_modules"]] == [
            (conflicted, ["espalier/cli.py"], _UNTIL)]
        cu = out["catch_ups"]
        assert (cu["prs"], cu["lowest_pr"], cu["catch_up_merges"], cu["conflicted_any_file"]) == (2, 5, 2, 1)
        assert cu["on_cli_modules"] == [{"oid": conflicted, "pr": 7, "paths": ["espalier/cli.py"]}]


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
        _write(repo / "a.txt", "a\n")
        _commit_all(repo, "lane a")
        _git(repo, "checkout", "-q", "main")
        _edit(repo, "    return 1\n", "    return 2\n")
        _commit_all(repo, "main brings a cli change")
        _git(repo, "checkout", "-q", "lane/a")
        _git(repo, "-c", "commit.gpgsign=false", "merge", "-q", "-m", "Merge branch 'main' into lane/a", "main")
        _git(repo, "checkout", "-q", "-b", "lane/b", "main")
        _write(repo / "b.txt", "b\n")
        _commit_all(repo, "lane b")
        _git(repo, "checkout", "-q", "main")
        _write(repo / "README.md", "readme\n")
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
        _write(repo / "espalier.toml", 'dispatcher = "air"\n')
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
        _write(repo / "espalier" / "cli.py", self._SHORT_THEN_LONG)
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
        _write(repo / "docs" / "x.md", "one\ntwo\n")
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
        _write(proj / "s1.jsonl", "".join(json.dumps(r) + "\n" for r in recs))

        def run(extra_checkouts=(), seen=None):
            ctx = _ctx(repo, _mail_at=mail, projects_dir=str(tmp_path / "projects"),
                       checkouts=[{"path": root, "seat": "air-work", "folder": "Proj-Work"}, *extra_checkouts])
            if seen is not None:
                seen.append(ctx)
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
        # the one seat read here is air-work: air, with no checkout in this clone, is named, never read as zeros
        assert out["seats"] == ["air-work"] and out["of_seats"] == 4
        assert out["seats_not_read"] == {"air": "no checkout of this clone reads as it"}
        assert out["calls"]["unlexed"]["own"] == out["calls"]["heredoc_tag_missed"]["own"] == {"commands": 0, "naming_cli": 0}

    def test_two_runs_at_one_pin_read_the_same_section(self, section):
        """Dies to: an unsorted walk or a clock read inside the section: two runs at one pin must
        print the same transcripts section (Pass criteria)."""
        first, second = section(), section()
        assert first["treatment"] and first["control"], "an equality of two empty reads proves nothing"
        assert json.dumps(first, sort_keys=True, default=sorted) == json.dumps(second, sort_keys=True, default=sorted)

    def test_a_checkout_whose_seat_cannot_be_read_is_named_not_dropped(self, section):
        """Dies to: a checkout with no seat read (its directory gone, so no config to read; or no
        `espalier.machine`) dropped from the population in silence: its transcripts are a box
        seat's or not, and the census cannot tell which."""
        out = section([{"path": "/gone/wt", "seat": None, "folder": "-gone-wt", "gone": True},
                       {"path": "/plain", "seat": None, "folder": "-plain"}])
        assert out["checkouts_without_a_seat"] == [
            {"path": "/gone/wt", "folder": "-gone-wt", "why": "directory gone"},
            {"path": "/plain", "folder": "-plain", "why": "no espalier.machine"}]
        assert section()["checkouts_without_a_seat"] == []

    def test_a_checkout_whose_config_git_cannot_read_is_named_by_that_failure(self, section):
        """Dies to: a `git config` that failed (a config file git cannot parse, exit 128) named as a
        checkout with no `espalier.machine`, a missing name, where its seat was never read
        (rv-sib F7); the census's own `checkouts` row carries the failure (see
        TestTheCheckoutsOfAClone)."""
        bad = {"path": "/bad", "seat": None, "folder": "-bad", "seat_error": "git config failed (exit 128): fatal"}
        assert section([bad])["checkouts_without_a_seat"] == [
            {"path": "/bad", "folder": "-bad", "why": "git config failed (exit 128): fatal"}]

    def test_a_never_named_worktree_with_a_folder_is_read_never_dropped(self, section, tmp_path):
        """Dies to: the skip widened to every never-named worktree (rv-sib m24), so one that does hold
        a transcript folder, a session having run in it, is dropped with its reads."""
        folder = tmp_path / "projects" / "-wt-agent-y"
        folder.mkdir()
        rec = {**_use("t9", "Read", "2020-01-01T01:30:00Z", "main", file_path="/wt/agent-y/docs/x.md"),
               "cwd": "/wt/agent-y"}
        _write(folder / "s9.jsonl",
               json.dumps(rec) + "\n" + json.dumps(_result("t9", "", {"file": {"numLines": 3}})) + "\n")
        out = section([{"path": "/wt/agent-y", "seat": "air-work", "folder": "-wt-agent-y", "own_name": False}])
        assert [(p["folder"], p["records"]) for p in out["population"]] == [("proj-work", 4), ("-wt-agent-y", 1)]
        assert out["skipped_never_named"] == []

    def test_a_command_the_lexer_refuses_is_counted_and_named_unread(self, section, tmp_path):
        """Dies to: a Bash command the lexer refuses booking no read and counted nowhere, so its
        reads are a silent zero (rv-c F2, rv-sib F5); or a heredoc the old per-line regex found and
        the scanner did not, with its delimiter line later in the command, left unflagged (item 15's
        check): each counted own and subagent apart, with those holding a CLI module's path."""
        refused = 'echo "$(echo "it\'s")" && sed -n 1,40p espalier/cli.py'
        missed = 'x="$(case a in a) cat <<EOF\nespalier/cli.py\nEOF\n;; esac)"'
        recs = [_use("t7", "Bash", "2020-01-01T01:20:00Z", "lane/a", command=refused),
                _result("t7", "", {"stdout": _lines(40)}),
                _use("t8", "Bash", "2020-01-01T01:25:00Z", "lane/a", command=missed),
                _result("t8", "", {"stdout": ""})]
        _write(tmp_path / "projects" / "proj-work" / "s2.jsonl", "".join(json.dumps(r) + "\n" for r in recs))
        seen: list[dict] = []
        out = section(seen=seen)
        assert out["calls"]["unlexed"] == {"own": {"commands": 1, "naming_cli": 1},
                                           "subagents": {"commands": 0, "naming_cli": 0}}
        assert out["calls"]["heredoc_tag_missed"] == {"own": {"commands": 1, "naming_cli": 1},
                                                      "subagents": {"commands": 0, "naming_cli": 0}}
        assert "own 1 (1 holding a CLI module's path)" in seen[0]["_partial_unread"]["transcripts"]["unlexed"]

    def test_a_worktree_never_named_with_no_folder_is_skipped_and_named(self, section):
        """Dies to: a linked worktree that answers a box seat only through the clone's shared
        config (a fork's `.claude/worktrees/agent-*`, which no session ever ran in) and holds no
        transcript folder refusing the whole section, so the census reads transcripts unread on
        any box with a fan-out's worktree live; or one skipped in silence, or skipped while its
        figures moved."""
        agent = {"path": "/wt/agent-x", "seat": "air", "folder": "-wt-agent-x", "own_name": False}
        out = section([agent])
        assert out["skipped_never_named"] == [{"path": "/wt/agent-x", "folder": "-wt-agent-x", "seat": "air"}]
        plain = section()
        assert plain["skipped_never_named"] == []
        assert (out["treatment"], out["control"], out["population"]) == (
            plain["treatment"], plain["control"], plain["population"])

    @pytest.mark.parametrize("own", [True, None], ids=["own-name", "scope-unread"])
    def test_a_seat_s_own_checkout_with_no_folder_stays_unread(self, section, own):
        """Dies to: the skip widened past a worktree read as never named: a checkout that carries
        the seat's name itself (or whose name's scope could not be read) and has no transcript
        folder is a seat's transcripts gone, and the section refuses rather than read a zero."""
        row = {"path": "/wt/named", "seat": "air", "folder": "-wt-named"}
        if own is not None:
            row["own_name"] = own
        with pytest.raises(_CENSUS.Unread, match="transcript folder"):
            section([row])

    def test_a_clone_with_no_box_seat_checkout_is_unread(self, repo, tmp_path):
        """Dies to: no checkout naming a box seat (an unnamed machine, a failed worktree list)
        read as a population of nothing: every lane 0 lines and the verdict `not real`."""
        (tmp_path / "projects").mkdir()
        ctx = _ctx(repo, _mail_at={}, projects_dir=str(tmp_path / "projects"),
                   checkouts=[{"path": str(repo), "seat": None, "folder": "x"}])
        with pytest.raises(_CENSUS.Unread, match="no checkout of this clone is a box seat"):
            _CENSUS.section_transcripts(ctx)

    def test_a_population_with_no_record_up_to_the_pin_is_unread(self, repo, tmp_path):
        """Dies to: a box seat's folder whose every record is stamped after the pin (or none at
        all) read as lanes that read nothing."""
        proj = tmp_path / "projects" / "proj"
        proj.mkdir(parents=True)
        late = _use("t1", "Read", "2020-01-03T00:00:00Z", "main", file_path=f"{repo}/espalier/cli.py")
        _write(proj / "s1.jsonl", json.dumps(late) + "\n")
        ctx = _ctx(repo, _mail_at={}, projects_dir=str(tmp_path / "projects"),
                   checkouts=[{"path": str(repo), "seat": "air", "folder": "proj"}])
        with pytest.raises(_CENSUS.Unread, match="hold no record up to"):
            _CENSUS.section_transcripts(ctx)


# ---------------------------------------------------------------- the review fold: a failed read is unread

def _raises(exc: BaseException):
    def reader(ctx):
        raise exc
    return reader


_READ_FAILURES = [
    subprocess.TimeoutExpired(["git", "show"], 120.0),
    FileNotFoundError(2, "No such file or directory", "git"),
    SyntaxError("invalid syntax"),
    ValueError("substring not found"),
    json.JSONDecodeError("Expecting value", "", 0),
    SystemExit("merge_cost_census: replay failed"),
]


class TestAFailedReadIsUnreadNeverAnAbort:
    @pytest.mark.parametrize("exc", _READ_FAILURES, ids=lambda e: type(e).__name__)
    def test_each_read_failure_names_its_section_and_the_rest_still_read(self, repo, monkeypatch, exc):
        """Dies to: `_section` catching `Unread` alone, so git past its timeout, a program or a
        file that is not there, a source that does not parse, a short read, bad JSON or a loaded
        census's `SystemExit` aborts the whole run and no section prints."""
        monkeypatch.setitem(_CENSUS.SECTION_READERS, "readers", _raises(exc))
        out = _CENSUS.census(repo, _head(repo), ["functions", "readers"])
        assert out["readers"] is None
        assert out["unread"]["readers"].startswith(type(exc).__name__ + ": ")
        assert out["functions"]["functions"] == 6

    def test_a_cli_that_does_not_parse_is_unread_not_an_abort(self, repo):
        """Dies to: `ast.parse` in `parse_cli` raising `SyntaxError` through the run, so a pin
        whose cli.py does not parse prints nothing where it should name what it cannot read."""
        _add(repo, {"espalier/cli.py": "def broken(:\n    pass\n"})
        out = _CENSUS.census(repo, _head(repo), ["functions", "layers"])
        assert out["functions"] is None and out["layers"] is None
        assert out["unread"]["functions"].startswith("SyntaxError: ")

    def test_a_collision_component_that_exits_is_unread_and_the_others_read(self, repo, monkeypatch):
        """Dies to: the replay's `SystemExit` (a scratch clone git refuses) escaping the collision
        section, so one failed component aborts the run and the catch-ups after it never print;
        or a component skipped by the caller read as an empty one."""
        _trunk(repo)

        def exits(ctx):
            raise SystemExit("merge_cost_census: git clone failed")

        monkeypatch.setattr(_CENSUS, "conflicts", exits)
        out = _CENSUS.census(repo, _head(repo), ["collision"],
                             extra={"skip_components": ("pairs", "claims", "holds")})["collision"]
        assert out["conflicts"] is None
        assert out["unread"]["conflicts"] == "SystemExit: merge_cost_census: git clone failed"
        assert out["catch_ups"] == {"graded": False, "catch_ups_in_window": 0, "carrying_a_cli_module": 0}
        assert out["pairs"] is None and out["unread"]["pairs"] == "skipped by the caller"

    @pytest.mark.parametrize("body, why", [(None, "FileNotFoundError"), ("{not json", "JSONDecodeError"),
                                           ('{"number": 1}', "malformed")], ids=["missing", "bad-json", "no-list"])
    def test_a_saved_pull_request_list_that_cannot_be_read_leaves_the_pairs_unread(self, repo, tmp_path, body, why):
        """Dies to: a `--prs-json` file that is not there, or holds bad JSON or no list, raising
        through the run (the whole census aborts) or read as no pull requests (every lane then
        reads as one with no open time)."""
        saved = tmp_path / "prs.json"
        if body is not None:
            _write(saved, body)
        _trunk(repo)
        out = _CENSUS.census(repo, _head(repo), ["collision"], extra={
            "prs_json": str(saved), "skip_components": ("conflicts", "claims", "holds", "catch_ups")})["collision"]
        assert out["pairs"] is None
        assert why in out["unread"]["pairs"] and "--prs-json" in out["unread"]["pairs"]

    def test_a_saved_pull_request_list_is_read_and_a_row_with_no_times_left_out(self, repo, tmp_path):
        """Dies to: `--prs-json` not read (then `gh` runs, which this tmp repo has no remote for),
        or a pull request with no `createdAt` given a stamp it does not have."""
        saved = tmp_path / "prs.json"
        _write(saved, json.dumps([
            {"number": 3, "createdAt": "2020-01-01T00:00:00Z", "mergedAt": "2020-01-01T01:00:00+00:00"},
            {"number": 4, "createdAt": None, "mergedAt": "2020-01-01T02:00:00Z"}]))
        assert _CENSUS.pr_meta(_ctx(repo, prs_json=str(saved))) == {
            3: {"created": "2020-01-01T00:00:00Z", "merged": "2020-01-01T01:00:00Z"}}

    def test_a_pin_without_pyproject_names_the_console_entry_unread(self, repo):
        """Dies to: `console_entry` set to None where the pin holds no pyproject.toml with nothing
        under unread, which reads as a console entry no move need keep."""
        out = _CENSUS.census(repo, _head(repo), ["importers"])
        assert out["importers"]["entry_points"]["console_entry"] is None
        assert "pyproject.toml is not in" in out["unread"]["importers.console_entry"]


class TestTheClustersWithTheImportersUnread:
    @staticmethod
    def _fails(root, at):
        raise _CENSUS.Unread("git ls-tree failed")

    def test_dead_is_no_claim_when_the_importers_cannot_be_read(self, repo, monkeypatch):
        """Dies to: the importers read failing in silence, so `unreached_dead` still names TABLE
        and Thing, which another module or a test may well import, with nothing under unread."""
        monkeypatch.setattr(_CENSUS, "tracked_at", self._fails)
        out = _CENSUS.census(repo, _head(repo), ["clusters"], extra={"concerns": {}})
        by = out["clusters"]["by_command"]
        assert (by["unreached_external"], by["unreached_tests_only"], by["unreached_dead"]) == (None, None, None)
        assert "git ls-tree failed" in out["unread"]["clusters.importers"]
        assert out["clusters"]["external_names_read"] is False

    def test_an_unsplit_definition_s_owner_is_unreached_and_unplaced(self, repo, monkeypatch):
        """Dies to: a definition the failed split cannot place read as dead, or as one cli does not
        define (`not_in_cli`), by the sections that name owners (probes, ledger rows, doctor)."""
        monkeypatch.setattr(_CENSUS, "tracked_at", self._fails)
        owners = _CENSUS._owners(_ctx(repo, concerns={}))
        assert owners["TABLE"] == {"unreached": None}
        assert owners["build_parser"] == {"unreached": "entry"}

    def test_a_concern_command_the_pin_does_not_hold_is_named(self, repo):
        """Dies to: a hand concern's command that is gone at the pin dropped in silence, so the
        concern is priced over fewer commands than its grouping names, with nothing said."""
        out = _CENSUS.census(repo, _head(repo), ["clusters"], extra={"concerns": {"pair": ("cmd_alpha", "cmd_gone")}})
        assert out["clusters"]["concerns"]["missing_commands"] == ["cmd_gone"]


class TestAFileThatDoesNotParseIsNamed:
    @pytest.fixture
    def out(self, repo):
        _add(repo, {**_MOVE_FILES,
                    "tests/test_bad.py": 'from espalier import cli\nKEYS = {("espalier/cli.py", "_core"): 1}\ndef f(:\n'})
        return _CENSUS.census(repo, _head(repo), ["readers", "importers", "patches", "move_cost"],
                              extra=dict(_MOVE_EXTRA))

    def test_each_section_that_parses_the_file_names_it(self, out):
        """Dies to: a file that fails `ast.parse` landing in `unparsed` with nothing under unread,
        so the readers, importers and patches figures read as complete while one file's sites
        (here a symbol key, an import and its alias loads) were never seen."""
        for part in ("readers.unparsed", "importers.unparsed", "patches.unparsed"):
            assert "tests/test_bad.py" in out["unread"][part]

    def test_the_move_cost_names_the_ingredients_it_reads_in_part(self, out):
        """Dies to: `_move_inputs` reading `symbol_keys`, the import tallies and the patch tallies
        as complete over a section read in part; they are kept (a lower bound) and named."""
        for k in ("symbol_keys", "test_imports", "importers_outside", "patch_sites", "patch_targets"):
            assert "lower bound" in out["unread"][f"move_cost.{k}"]
        assert out["move_cost"]["sums"]["symbol_keys"]["section_total"] == 3


class TestAFileGitCannotReadIsNamed:
    def test_each_section_reading_the_tracked_texts_names_what_it_could_not_read(self, repo):
        """Dies to: `_tracked_texts`' unread files (here a gitlink, which `cat-file` reports
        missing) surfaced only as the citations section's `files_unread`, so the readers,
        probes, ledger rows and citations figures read as complete with nothing under unread."""
        _add(repo, _CITING)
        _git(repo, "update-index", "--add", "--cacheinfo", "160000,1111111111111111111111111111111111111111,sub")
        _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "a gitlink")
        _CENSUS.source_at.cache_clear()
        out = _CENSUS.census(repo, _head(repo), ["readers", "citations", "probes", "ledger_rows"], extra={"concerns": {}})
        for section in ("readers", "citations", "probes", "ledger_rows"):
            assert "['sub']" in out["unread"][f"{section}.texts"]
        assert out["citations"]["files_unread"] == ["sub"]


class TestTheLaneReadOfAModuleTheBaseDoesNotHold:
    def test_a_module_the_lane_adds_reads_no_definition_and_no_crash(self, repo):
        """Dies to: the early return for a module absent at the merge-base carrying no
        `by_definition`, so `section_lane_read` raises KeyError on the first lane that adds a CLI
        module (a move's new module: the very lane the census is for)."""
        _trunk(repo)
        _git(repo, "checkout", "-q", "-b", "lane/n", "main")
        _write(repo / "espalier" / "newmod.py", "def f():\n    return 1\n")
        _edit(repo, "    return 1\n", "    return 2\n")
        _commit_all(repo, "a new module")
        _land(repo, 1, "lane/n")
        ctx = _ctx(repo)
        ctx["modules"] = (_CENSUS.CLI, "espalier/newmod.py")
        out = _CENSUS.section_lane_read(ctx)
        assert out["rows"] == [{"pr": 1, "lines": 2, "definitions": ["_helper"]}]

    def test_a_read_git_fails_is_unread_and_an_absent_path_none(self, repo):
        """Dies to: `source_at` returning None on any failure of git (a commit git cannot find,
        which git words as a path not in it), so a failed read reads as a file the commit does
        not hold, of length 0."""
        _CENSUS.source_at.cache_clear()
        assert _CENSUS.source_at(repo, _head(repo), "nope.py") is None
        with pytest.raises(_CENSUS.Unread, match="failed"):
            _CENSUS.source_at(repo, "1" * 40, "espalier/cli.py")


class TestTheHoldsWhereTheRecordIsMissingOrOutOfOrder:
    @pytest.fixture
    def toml(self, repo):
        _write(repo / "espalier.toml", 'dispatcher = "air"\n')
        _commit_all(repo, "toml")
        return repo

    def test_a_dispatcher_with_no_mail_at_the_pin_is_unread(self, toml):
        """Dies to: a dispatcher the mail refs do not hold read as one that held nothing
        (`declared: []`, a measured zero)."""
        with pytest.raises(_CENSUS.Unread, match="no mail of the dispatcher 'air'"):
            _CENSUS.holds(_ctx(toml, _mail_at={"other": []}))

    def test_the_record_starts_at_the_earliest_message_in_any_order(self, toml):
        """Dies to: the record's start read off the file's first line, which a mail file whose
        lines are not in stamp order does not hold."""
        messages = list(reversed(TestTheHolds._MESSAGES))
        out = _CENSUS.holds(_ctx(toml, _mail_at={"air": messages}))
        assert out["record_from"] == "2020-01-01T03:04:05Z" and out["record_days"] == 1.0


class TestACatchUpDiffGitCannotGiveIsUnread:
    def test_a_failed_diff_is_unread_never_a_catch_up_that_carried_nothing(self, repo, monkeypatch):
        """Dies to: `if rc == 0 and _touches_cli(...)` counting a `git diff` that failed as a
        catch-up that brought no CLI change."""
        _trunk(repo)
        _git(repo, "checkout", "-q", "-b", "lane/a", "main")
        _write(repo / "a.txt", "a\n")
        _commit_all(repo, "lane a")
        _git(repo, "checkout", "-q", "main")
        _edit(repo, "    return 1\n", "    return 2\n")
        _commit_all(repo, "main brings a cli change")
        _git(repo, "checkout", "-q", "lane/a")
        _git(repo, "-c", "commit.gpgsign=false", "merge", "-q", "-m", "Merge branch 'main' into lane/a", "main")
        ctx = _ctx(repo)
        real = _CENSUS.git

        def diff_fails(root, *args):
            return (128, "", "fatal: bad object") if args[:1] == ("diff",) else real(root, *args)

        monkeypatch.setattr(_CENSUS, "git", diff_fails)
        with pytest.raises(_CENSUS.Unread, match="git diff"):
            _CENSUS.catch_ups_carrying(ctx)


# ---------------------------------------------------------------- the review fold: git output by NUL

class TestGitOutputIsSplitOnNul:
    def test_a_path_git_would_quote_is_read_as_itself(self, repo):
        """Dies to: `git ls-tree` without `-z`, which quotes a path holding a non-ASCII byte
        (`"tests/test_caf\\303\\251.py"`): the quoted name then reads as no file, so its patch
        site and its citation are dropped and the file is named unread."""
        _add(repo, {**_CITING,
                    "tests/test_café.py": 'from espalier import cli\n\n\ndef test_x(monkeypatch):\n'
                                          '    monkeypatch.setattr(cli, "_helper", None)\n',
                    "docs/café.md": "See `espalier/cli.py::_reader`.\n"})
        out = _CENSUS.census(repo, _head(repo), ["patches", "citations"])
        assert (out["patches"]["sites"], out["patches"]["files"]) == (1, 1)
        assert out["citations"]["files_unread"] == []
        assert out["citations"]["per_symbol"]["_reader"] == {"struck/struck_fragments": 1, "swept_live/docs": 1}

    def test_a_lane_s_files_name_a_path_git_would_quote_as_itself(self, repo):
        """Dies to: `git diff --name-only` without `-z`, so a lane that edits `docs/café.md`
        lists a quoted name no lane edited (a control lane's E then misses its reads)."""
        _trunk(repo)
        _git(repo, "checkout", "-q", "-b", "lane/u", "main")
        (repo / "docs").mkdir()
        _write(repo / "docs" / "café.md", "x\n")
        _commit_all(repo, "u")
        _land(repo, 1, "lane/u")
        (pr,) = _CENSUS._prs(_ctx(repo))
        assert pr["files"] == ["docs/café.md"]

    def test_a_subject_holding_a_line_separator_is_one_record(self, repo):
        """Dies to: `git log` output split with `splitlines`, which also splits at U+2028: a merge
        subject holding one breaks into two rows (the second has no date, and `_stamp('')`
        raises), and a lane commit's subject into a phantom second commit."""
        _trunk(repo)
        _git(repo, "checkout", "-q", "-b", "lane/s", "main")
        _edit(repo, "    return 1\n", "    return 2\n")
        _commit_all(repo, "edit\u2028beside a separator")
        _git(repo, "checkout", "-q", "main")
        _git(repo, "-c", "commit.gpgsign=false", "merge", "-q", "--no-ff", "-m",
             "Merge pull request #1 from owner/lane/s\u2028and more", "lane/s")
        rows = _CENSUS.merges_at(repo, _head(repo))
        assert len(rows) == 1 and rows[0]["subject"].endswith("\u2028and more")
        (pr,) = _CENSUS.pr_merges(repo, _head(repo))
        assert [c["messageHeadline"] for c in _CENSUS.lane_commits(repo, pr)] == ["edit\u2028beside a separator"]

    def test_the_file_s_lines_are_counted_as_ast_numbers_them(self, repo):
        """Dies to: the file's lines counted with `splitlines`, which also breaks a line at a form
        feed and at \\x85 where Python's tokenizer does not, so `lines` and `file_lines` run past
        the last ast line number."""
        text = _CLI_FIXTURE.replace("_LATCH = False\n", "_LATCH = False\n\x0c\n# a page\x85 break\n")
        _add(repo, {"espalier/cli.py": text})
        out = _CENSUS.census(repo, _head(repo), ["functions", "clusters"], extra={"concerns": {}})
        last = max(n.end_lineno for n in ast.parse(text).body)
        assert out["functions"]["lines"] == out["clusters"]["file_lines"] == last

    def test_a_rule_s_digest_reads_its_lines_where_ast_places_them(self):
        """Dies to: `rule_digest` indexing `splitlines()` by ast line numbers, so a form feed above
        the function shifts every line it reads and the pinned digest goes unmatched."""
        body = "def _is_struck_row(line):\n    return line.startswith('|')\n"
        assert _CENSUS.rule_digest("# page\x0c one\n\n" + body, "_is_struck_row") == \
            _CENSUS.rule_digest("# page one\n\n" + body, "_is_struck_row")


class TestTheBatchReadKeepsEachPathToItsOwnText:
    def test_a_tree_entry_s_body_is_stepped_over(self, repo):
        """Dies to: a non-blob entry (a tree) skipped before its body is stepped over, so the next
        path's header is read out of the tree's bytes and a later path takes another's text."""
        _add(repo, {"docs/a.md": "alpha\n"})
        assert _CENSUS.blobs_at(repo, _head(repo), ["espalier", "docs/a.md", "nope.md"]) == {"docs/a.md": "alpha\n"}

    def test_a_reply_cut_short_is_unread_never_a_short_text(self, repo, monkeypatch):
        """Dies to: a body the batch cut short decoded as the file's whole text."""
        def short(argv, **_kw):
            return subprocess.CompletedProcess(argv, 0, stdout=b"0123 blob 10\nshort", stderr=b"")

        monkeypatch.setattr(_CENSUS, "run_bounded", short)
        with pytest.raises(_CENSUS.Unread, match="short"):
            _CENSUS.blobs_at(repo, "HEAD", ["a.md"])

    def test_a_submodule_header_carries_no_body(self, repo, monkeypatch):
        """Dies to: the bodiless `<oid> submodule` header newer git writes for a gitlink path (the
        CI cells' git; the Air's 2.39 writes none) read as a header it cannot read, so the whole
        read failed where the one path should go unread (#725's test (3.12) and (3.14) reds)."""
        def reply(argv, **_kw):
            return subprocess.CompletedProcess(argv, 0, stdout=b"1111 submodule\n2222 blob 6\nalpha\n\n",
                                               stderr=b"")

        monkeypatch.setattr(_CENSUS, "run_bounded", reply)
        assert _CENSUS.blobs_at(repo, "HEAD", ["tests/test_sub.py", "docs/a.md"]) == {"docs/a.md": "alpha\n"}


class TestAFixtureIsTheSameBytesOnEveryPlatform:
    def test_a_committed_fixture_holds_the_bytes_the_test_wrote(self, repo, monkeypatch):
        """Dies to: ``_add`` writing in text mode, read here on any host with ``write_text``
        made to translate as Windows does (each ``\\n`` written as ``\\r\\n``): the blob then
        holds CRLF where the test wrote LF, the windows-latest red of
        ``test_a_tree_entry_s_body_is_stepped_over`` (#725's and #726's portability leg)."""
        real = pathlib.Path.write_text

        def windows_write_text(self, data, encoding=None, errors=None, newline=None):
            return real(self, data, encoding=encoding, errors=errors, newline="\r\n" if newline is None else newline)

        monkeypatch.setattr(pathlib.Path, "write_text", windows_write_text)
        _add(repo, {"docs/a.md": "alpha\n"})
        assert (repo / "docs" / "a.md").read_bytes() == b"alpha\n"
        blob = subprocess.run(["git", "cat-file", "blob", "HEAD:docs/a.md"], cwd=repo, capture_output=True,
                              env=_git_env(), check=True, timeout=45).stdout
        assert blob == b"alpha\n"

    def test_no_fixture_in_this_file_is_written_in_text_mode(self):
        """Dies to: a fixture written in text mode with no ``newline`` (``write_text``, or an
        ``open`` whose mode writes, appends or creates without ``b``), whose file holds CRLF on
        Windows alone, so a test asking its exact bytes reds on windows-latest and nowhere a
        required check runs. Each fixture goes through ``_write``, or opens in binary."""
        def translates(call):
            newline = next((k.value for k in call.keywords if k.arg == "newline"), None)
            return newline is None or (isinstance(newline, ast.Constant) and newline.value is None)

        def mode(call):
            pos = 0 if isinstance(call.func, ast.Attribute) else 1
            given = call.args[pos] if len(call.args) > pos else next(
                (k.value for k in call.keywords if k.arg == "mode"), None)
            return given.value if isinstance(given, ast.Constant) and isinstance(given.value, str) else "r"

        tree = ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))
        text_mode = []
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
            if name == "write_text" or (name == "open" and set(mode(n)) & set("wax") and "b" not in mode(n)):
                if translates(n):
                    text_mode.append(n.lineno)
        assert text_mode == []


# ---------------------------------------------------------------- the review fold: reads the census missed

class TestAPatchOnCliReachedThroughAnImportCall:
    _TEST = '''\
import importlib
import sys


def test_it(monkeypatch):
    monkeypatch.setattr(__import__("espalier.cli").cli, "_helper", lambda: 2)
    with monkeypatch.context() as m:
        m.setattr(importlib.import_module("espalier.cli"), "_reader", lambda: 0)
    monkeypatch.setattr(getattr(importlib.import_module("espalier." + "cli"), "os"), "sep", "/")
    monkeypatch.setattr(sys.modules[__name__], "FLAG", 1)
'''

    def test_each_import_call_spelling_of_cli_is_a_site_and_a_dynamic_owner_is_counted(self, repo):
        """Dies to: `_dotted` returning None for a call, so `__import__("espalier.cli").cli` and
        `importlib.import_module("espalier.cli")` patch cli unseen (tests/test_bounded_spawn.py's
        `_git_ignorecase` at 3330a5a), or an owner the census cannot resolve dropped uncounted."""
        _add(repo, {"tests/test_imp.py": self._TEST})
        out = _CENSUS.census(repo, _head(repo), ["patches"])["patches"]
        assert (out["sites"], out["targets"]) == (2, 2)
        assert sorted(out["per_target"]) == ["_helper", "_reader"]
        assert out["unresolved_owner"] == {"calls": 2, "by_file": {"tests/test_imp.py": 2}}


#: Each command, the one Bash call it is, and the reads the census books for it (40 lines out).
_SHELL_ROWS = [
    ("# the dispatch\nsed -n 1,40p espalier/cli.py", [("espalier/cli.py", 40)]),
    ("cd /work/repo\n# look\nsed -n 1,40p espalier/cli.py", [("espalier/cli.py", 40)]),
    ("sed -n 1,40p espalier/cli.py # the first forty", [("espalier/cli.py", 40)]),
    ("sed -n 1,40p \\\n  espalier/cli.py", [("espalier/cli.py", 40)]),
    ('cat <<< "x"\nsed -n 1,40p espalier/cli.py', [("espalier/cli.py", 40)]),
    ("sed -n 1,40p < espalier/cli.py", [("espalier/cli.py", 40)]),
    ("head -c 400 espalier/cli.py", [("espalier/cli.py", 40)]),
    ("git --no-pager show HEAD:espalier/cli.py", [("espalier/cli.py", 40)]),
    ("git -P -c core.pager=cat -C /work/repo show HEAD:espalier/cli.py", [("espalier/cli.py", 40)]),
    # a `#` inside a word is the word's: the lexer's own comment character would drop the sed after it
    ("x=abc; echo ${#x}; sed -n 1,40p espalier/cli.py", [("espalier/cli.py", 40)]),
    ("echo a#b && sed -n 1,40p espalier/cli.py", [("espalier/cli.py", 40)]),
]


class TestTheShellIsReadAsTheShellReadsIt:
    @pytest.mark.parametrize("command, reads", _SHELL_ROWS, ids=[f"row{i}" for i in range(len(_SHELL_ROWS))])
    def test_a_read_the_shell_runs_is_booked(self, command, reads):
        """Dies to: a `#` comment line dropping every later line (shlex's own commenters over a
        `" ; "`-joined text, or `lex.commenters` left at shlex's `#`, which cuts at `${#x}` and
        `a#b`), a backslash-newline splitting one command in two, a here-string matching the
        heredoc pattern and stripping the rest, a file fed on stdin read as never a read, `head -c`'s
        count taken as a file, or git's global options left in front of `show`."""
        calls = _calls([_use("t1", "Bash", "2020-01-01T01:00:00Z", "lane/a", command=command),
                        _result("t1", "", {"stdout": _lines(40)})])
        assert [c["reads"] for c in calls] == [reads]

    @pytest.mark.parametrize("command, text", [
        ("echo ${#x} a#b '#q' \"#d\" # c", "echo ${#x} a#b '#q' \"#d\" "),
        ("echo a\\ #b", "echo a\\ #b"),
        ("x=1 # c\ny=2", "x=1 \ny=2"),
        ('python3 -c "\n# inside the quotes\nprint(1)"', 'python3 -c "\n# inside the quotes\nprint(1)"'),
        ("echo 'a\\\nb' \\\nc", "echo 'a\\\nb' c"),
    ], ids=["word-starts", "escaped-space", "per-line", "multi-line-quote", "continuation"])
    def test_a_comment_is_a_word_starting_hash_outside_quotes_and_ends_at_its_line(self, command, text):
        """Dies to: a `#` inside a word, a quote or `${#x}` read as a comment, a comment taking the
        lines after its own, or a backslash-newline joined inside single quotes."""
        assert _CENSUS.shell_text(command) == text

    _READ = "\nsed -n 1,40p espalier/cli.py"

    @pytest.mark.parametrize("command, text", [
        ("echo $((1 << n))" + _READ, "echo $((1 << n))" + _READ),
        ("(( x = 1 << n ))" + _READ, "(( x = 1 << n ))" + _READ),
        ('python3 -c "print(1 << n)"' + _READ, 'python3 -c "print(1 << n)"' + _READ),
        ("awk 'BEGIN { s = \"<< n\" }' f" + _READ, "awk 'BEGIN { s = \"<< n\" }' f" + _READ),
        ("# feed it with << EOF later" + _READ, "# feed it with << EOF later" + _READ),
        ('echo "one\n<< n"' + _READ, 'echo "one\n<< n"' + _READ),
        ("cat <<'EOF' > f\nespalier/cli.py\nEOF" + _READ, "cat <<'EOF' > f" + _READ),
        ("git commit -m \"$(cat <<'EOF'\nfix espalier/cli.py\nEOF\n)\"" + _READ,
         "git commit -m \"$(cat <<'EOF'\n)\"" + _READ),
        ("echo $((1<<2)); python3 - <<EOF\nprint(1)\nEOF" + _READ, "echo $((1<<2)); python3 - <<EOF" + _READ),
        ("cat <<-END\n\tespalier/cli.py\n\tEND" + _READ, "cat <<-END" + _READ),
        ("echo $'it\\'s' && cat <<EOF\nespalier/cli.py\nEOF" + _READ, "echo $'it\\'s' && cat <<EOF" + _READ),
        ("x=\"$(cd d && (ls) && cat <<'EOF'\nespalier/cli.py\nEOF\n)\"" + _READ,
         "x=\"$(cd d && (ls) && cat <<'EOF'\n)\"" + _READ),
        ("echo \\\"; cat <<EOF\nespalier/cli.py\nEOF" + _READ, "echo \\\"; cat <<EOF" + _READ),
        ('echo "a\\"b"; cat <<EOF\nespalier/cli.py\nEOF' + _READ, 'echo "a\\"b"; cat <<EOF' + _READ),
    ], ids=["arith-expansion", "arith-command", "double-quoted", "single-quoted", "comment",
            "quote-carried", "heredoc", "heredoc-in-command-substitution-in-quotes",
            "heredoc-after-arith", "tab-stripped", "ansi-c-quote-escapes-its-quote",
            "subshell-inside-substitution", "escaped-quote", "escaped-quote-in-double-quotes"])
    def test_a_heredoc_is_an_operator_the_shell_reads_and_nothing_else(self, command, text):
        """Dies to: a `<<` the shell never reads as a redirection (inside `$((...))` or `((...))`,
        inside quotes, or in a comment) taken for a heredoc, which strips every later line of the
        command and with them its reads; or a real heredoc left in, including the one inside a
        double-quoted `$(...)` (the commit-message shape), whose body would then be read as
        commands."""
        assert _CENSUS.strip_heredocs(command) == text

    def test_the_lexer_splits_on_the_operators_and_marks_the_pipe(self):
        """Dies to: the pipe's two sides not marked (then a piped read is charged whole), or `&&`
        not splitting one simple command from the next."""
        assert _CENSUS.simple_commands("cat a | head -3 && sed -n 1p b") == [
            (["cat", "a"], True), (["head", "-3"], True), (["sed", "-n", "1p", "b"], False)]
        assert _CENSUS.simple_commands("# the dispatch\nsed -n 1,40p espalier/cli.py") == [
            (["sed", "-n", "1,40p", "espalier/cli.py"], False)]

    @pytest.mark.parametrize("argv, got", [
        (["head", "-n", "5", "a"], ("read", ["a"], 5)),
        (["head", "-5", "a"], ("read", ["a"], 5)),
        (["head", "a"], ("read", ["a"], 10)),
        (["tail", "-n", "+3", "a"], ("read", ["a"], None)),
        (["head", "-c", "100", "a"], ("read", ["a"], None)),
        (["sed", "-n", "2,7p", "a"], ("read", ["a"], 6)),
        (["sed", "-i", "s/a/b/", "a"], None),
        (["awk", "-f", "prog.awk", "a"], ("read", ["a"], None)),
        (["cat", "a", ">", "b"], ("read", ["a"], None)),
        (["cat", "a", "2>/dev/null"], ("read", ["a"], None)),
        (["X=1", "cat", "a"], ("read", ["a"], None)),
        (["cat", "<<", "EOF"], ("read", [], None)),
        (["cat", "<<<", "word"], ("read", [], None)),
        (["cat", "<a"], ("read", ["a"], None)),
        (["git", "show", "HEAD:a", "b:c"], ("read", ["a", "c"], None)),
        (["git", "--git-dir=.git", "--work-tree", ".", "show", "HEAD:a"], ("read", ["a"], None)),
        (["git", "grep", "-n", "foo", "a", "b"], ("search", ["a", "b"], None)),
        (["rg", "foo", "a"], ("search", ["a"], None)),
        (["echo", "a"], None),
    ])
    def test_each_operand_shape_is_read_by_its_rule(self, argv, got):
        """Dies to: an option's argument taken as a file (`-n 5`, `-c 100`, `-f prog.awk`), a
        written target or a heredoc tag read as one, a sed script read as a file, `sed -i` read
        as a read, or a range read from the wrong option."""
        assert _CENSUS.read_operands(argv) == got


# ---------------------------------------------------------------- the review fold: scope and bucketing

_SCOPED_CLI = '''\
import os


def helper():
    return 1


def other():
    return 2


def outer():
    key = lambda helper: helper
    rows = [other for other in range(3)]
    return helper(), key, rows


def nested():
    def inner(helper=helper):
        return helper
    return inner


def nonlocal_user():
    other = 1

    def inner():
        nonlocal other
        other = 2
        return other
    return inner


class Holder:
    helper = 3

    def method(self):
        return helper()


def walrus():
    return [(other := x) for x in range(2)], other


def handler():
    try:
        return os.sep
    except ValueError as helper:
        return helper


def writer():
    def inner():
        global other
        other = 3
    return inner


def shadow_global():
    global other

    def inner():
        other = 1
        return other
    return other
'''


def _symtable_globals(text: str) -> dict[str, set[str]]:
    """Each top-level function's and class's module names by Python's own symbol table: every
    name it, or a scope nested in it, reads as global."""
    def names(table) -> set[str]:
        found = {s.get_name() for s in table.get_symbols() if s.is_referenced() and s.is_global()}
        for child in table.get_children():
            found |= names(child)
        return found
    return {t.get_name(): names(t) for t in symtable.symtable(text, "cli.py", "exec").get_children()}


class TestNamesResolveScopeByScope:
    @pytest.fixture
    def graph(self, repo):
        _add(repo, {"espalier/cli.py": _SCOPED_CLI})
        tree, defs = _CENSUS.parse_cli(repo, _head(repo))
        return defs, _CENSUS.graph(tree, defs)

    def test_a_nested_scope_s_binding_shadows_only_inside_it(self, graph):
        """Dies to: names bound anywhere inside a definition pooled as its own locals, so a
        lambda's parameter, a comprehension's target, a nested function's parameter or a class
        body's name hides the definition's real load of the module's `helper`; or a nested
        function's local store of a name the outer declares `global` read as a write."""
        _defs, g = graph
        edges = g["edges"]
        assert (edges["outer"], edges["nested"], edges["Holder"]) == (["helper"], ["helper"], ["helper"])
        assert (edges["nonlocal_user"], edges["walrus"], edges["handler"]) == ([], [], [])
        assert g["writes"] == {"writer": ["other"]}
        assert edges["shadow_global"] == ["other"]

    def test_the_loads_agree_with_symtable_on_every_definition(self, graph):
        """Dies to: any scope rule `_module_refs` gets wrong where Python's symbol table, the
        oracle, gets it right: each definition's loads are the module definitions it, or a scope
        in it, reads as global."""
        defs, g = graph
        names = {d["name"] for d in defs}
        oracle = _symtable_globals(_SCOPED_CLI)
        for d in defs:
            if d["kind"] != _CENSUS.NAME:
                assert g["loads"][d["name"]] == sorted((oracle[d["name"]] & names) - {d["name"]}), d["name"]

    _MORE = ("def helper():\n    return 1\n\n\n"
             "def first_iterable():\n    return [helper for helper in helper()]\n\n\n"
             "def local_def():\n    def helper():\n        return 0\n    return helper()\n")

    def test_a_first_iterable_and_a_nested_def_s_name_resolve_where_python_puts_them(self, repo):
        """Dies to: a comprehension's first iterable read inside the comprehension (rv-ab M31), where
        its own target `helper` hides the module's `helper` the iterable calls; or a nested def's
        name not bound in its function (M37), so the function's call of its own `helper` reads as a
        load of the module's. Python's symbol table is the oracle."""
        _add(repo, {"espalier/cli.py": self._MORE})
        tree, defs = _CENSUS.parse_cli(repo, _head(repo))
        g = _CENSUS.graph(tree, defs)
        assert (g["edges"]["first_iterable"], g["edges"]["local_def"]) == (["helper"], [])
        oracle = _symtable_globals(self._MORE)
        for name in ("first_iterable", "local_def"):
            assert g["loads"][name] == sorted((oracle[name] & {d["name"] for d in defs}) - {name}), name

    def test_a_module_level_name_definition_s_loads_are_edges(self, repo):
        """Dies to: a module-level name's own loads (a dispatch table) left out of the graph, so a
        command reached only through the table reads as reached by nothing."""
        _add(repo, {"espalier/cli.py": _CLI_FIXTURE + '\n\nHANDLERS = {"alpha": cmd_alpha, "key": lambda cmd_beta: cmd_beta}\n'})
        tree, defs = _CENSUS.parse_cli(repo, _head(repo))
        assert _CENSUS.graph(tree, defs)["edges"]["HANDLERS"] == ["cmd_alpha"]


class TestAnImportAtModuleLevelIsTopLevel:
    def test_an_import_in_a_module_level_try_or_if_is_not_lazy(self):
        """Dies to: `lazy` read off `tree.body` alone, so `try: from espalier.cli import main` at
        module level (it runs at import time) reads as an import inside a function."""
        tree = ast.parse("try:\n    from espalier.cli import main\nexcept ImportError:\n    main = None\n"
                         "if True:\n    from espalier import cli as _cli\nX = _cli.TABLE\n\n\n"
                         "def f():\n    from espalier.cli import Thing\n    return Thing\n")
        found = {(f["via"], tuple(f["names"])): f["lazy"] for f in _CENSUS.imports_of_cli("espalier/x.py", tree)}
        assert found == {("from", ("main",)): False, ("from", ("Thing",)): True, ("alias _cli", ("TABLE",)): False}


class TestAPatchOfCliIsBucketedOneWay:
    _TEST = '''\
from unittest import mock

from espalier import cli
from espalier import cli as _cli


def test_it(monkeypatch):
    monkeypatch.setitem(cli.REG, "k", 1)
    with mock.patch.dict(cli.REG, {}):
        pass
    with mock.patch.dict("espalier.cli.REG", {}):
        pass
    monkeypatch.setitem(cli.os.environ, "K", "1")
    something.object(cli, "Z")
    dict(cli.TABLE)


def test_fixture(cli, monkeypatch):
    cli.Y = 1
    monkeypatch.setattr(cli, "W", 1)
    monkeypatch.setattr(_cli, "V", 1)
'''

    def test_setitem_and_patch_dict_patch_cli_s_own_dict_in_every_spelling(self, repo):
        """Dies to: `setitem(cli.REG, "k", v)` booked as `REG.k` through cli and
        `patch.dict(cli.REG)` as `REG`, while `patch.dict("espalier.cli.REG")` is a cli target:
        one patch of cli's own dict bucketed two ways. `cli.os.environ` is another module's."""
        _add(repo, {"tests/test_bucket.py": self._TEST})
        out = _CENSUS.census(repo, _head(repo), ["patches"])["patches"]
        assert out["per_target"]["REG"] == {"sites": 3, "loaders": 0}
        assert out["through_cli"] == {"sites": 1, "targets": ["os.environ"]}

    def test_a_call_that_patches_nothing_and_a_shadowed_alias_are_no_sites(self, repo):
        """Dies to: `_PATCHERS` matched on the last attribute alone (`something.object(cli, "Z")`
        and a builtin `dict(...)` read as patches), a fixture parameter named `cli` read as the
        import it shadows (it is a parameter the census cannot resolve), or that parameter
        hiding a patch through another alias of cli (`_cli`, still the import). The call on an
        unknown base that reaches cli is unresolved: with the shadowed `cli.Y` and `W`, 3."""
        _add(repo, {"tests/test_bucket.py": self._TEST})
        out = _CENSUS.census(repo, _head(repo), ["patches"])["patches"]
        assert sorted(out["per_target"]) == ["REG", "V"]
        assert out["unresolved_owner"] == {"calls": 3, "by_file": {"tests/test_bucket.py": 3}}


class TestANamespaceIsReadInItsOwnScope:
    def test_a_namespace_built_in_one_function_is_no_argument_in_another(self):
        """Dies to: the module scope walked whole, so a Namespace one function builds flags a
        call in another (b takes `ns` as its parameter), while one the module builds and a
        function passes on (c) is still flagged."""
        tree = ast.parse("from argparse import Namespace\nfrom espalier.cli import cmd_x\nSHARED = Namespace(top=1)\n\n"
                         "def a():\n    ns = Namespace(one=1)\n    return 0\n\n"
                         "def b(ns):\n    return cmd_x(ns)\n\n"
                         "def c():\n    return cmd_x(SHARED)\n\n"
                         "def d():\n    ns = Namespace(two=2)\n    return cmd_x(ns)\n")
        assert _CENSUS.namespace_calls(tree, {"cmd_x"}, set()) == [
            {"name": "cmd_x", "line": 13, "attributes": ["top"]}, {"name": "cmd_x", "line": 17, "attributes": ["two"]}]

    def test_a_class_body_s_namespace_is_seen_from_the_body_and_never_from_a_method(self):
        """Dies to: a class body's names seen from a method defined in it (rv-ab M46), which Python
        never does: `ns` in `m` is the module's (unbound here), so only the class body's own call
        (line 7) is handed the Namespace."""
        tree = ast.parse("from argparse import Namespace\nfrom espalier.cli import cmd_x\n\n\n"
                         "class K:\n    ns = Namespace(k=1)\n    r = cmd_x(ns)\n\n"
                         "    def m(self):\n        return cmd_x(ns)\n")
        assert _CENSUS.namespace_calls(tree, {"cmd_x"}, set()) == [{"name": "cmd_x", "line": 7, "attributes": ["k"]}]


class TestALatchReadsItsOwnInitialValue:
    def test_a_tuple_unpacked_or_signed_name_reads_its_own_value(self):
        """Dies to: a tuple-unpacked latch (`_A, _B = False, None`) read as `tuple`, a signed
        number as `unaryop`, or every other constant named by one type (`int`), so a bool or
        None latch leaves the split latches it belongs to."""
        tree = ast.parse("_A, _B = False, None\n_C: bool = True\n_D = _E = None\n_F = -1\n_G = 'x'\n_H = 2.5\n_I = {}\n")
        assert {d["name"]: _CENSUS._initial_value(d) for d in _CENSUS.definitions(tree)} == {
            "_A": "bool", "_B": "None", "_C": "bool", "_D": "None", "_E": "None", "_F": "int", "_G": "str",
            "_H": "float", "_I": "dict"}


# ---------------------------------------------------------------- the review fold: tests that could not fail

class TestThePinIsReadInUtc:
    def test_an_offset_stamp_is_read_as_the_same_instant_in_utc(self):
        """Dies to: `_iso_z` formatting the stamp's own clock time with a `Z`, so a committer
        date at +02:00 reads two hours late and every window shifts."""
        assert _CENSUS._iso_z(datetime(2020, 1, 2, 5, 4, 5, tzinfo=timezone(timedelta(hours=2)))) == "2020-01-02T03:04:05Z"
        assert _CENSUS._stamp("2020-01-02T05:04:05+02:00") == _CENSUS._stamp("2020-01-02T03:04:05Z")


class TestTheGraphAlgorithms:
    def test_a_cycle_is_one_component_and_the_order_is_bottom_up(self):
        """Dies to: Tarjan's low-link not carried up from a child, so a cycle a -> b -> c -> a
        splits into three components, or the components out of their bottom-up order."""
        edges = {"a": ["b"], "b": ["c"], "c": ["a"], "d": ["a"], "e": []}
        assert _CENSUS.sccs(edges) == [["a", "b", "c"], ["d"], ["e"]]

    def test_a_closure_never_enters_a_stopped_node(self):
        """Dies to: `stop` ignored, so a command's closure runs on through another command."""
        assert _CENSUS.closure({"a": ["b"], "b": ["c"], "c": []}, ["a"], stop={"b"}) == {"a"}

    def test_an_edge_into_a_higher_unit_is_a_cycle_and_one_inside_or_below_is_not(self):
        """Dies to: `order_cycles` never emitting, or counting an edge inside its own unit (`>=`)."""
        edges = {"a": ["b", "a2"], "a2": [], "b": ["a"]}
        units = [("low", {"a", "a2"}), ("high", {"b"})]
        assert _CENSUS.order_cycles(edges, units) == [{"unit": "low", "member": "a", "calls": "b", "above": "high"}]
        assert _CENSUS.order_cycles({"a": ["a2"], "a2": []}, [("low", {"a", "a2"})]) == []

    def test_a_tie_pulled_in_is_closed_under_what_it_calls(self):
        """Dies to: the tie-closed set grown by the tie's users alone, never re-closed, so a pulled
        writer's own callee (`h`) is left behind."""
        edges = {"r": ["L"], "s": ["L", "h"], "h": [], "L": []}
        assert _CENSUS.tie_closure(edges, {"r", "L"}, {"L": ("latch", {"r", "s"})}, set()) == {"r", "L", "s", "h"}

    def test_a_definition_in_a_module_level_if_or_try_is_top_level(self):
        """Dies to: `_top_statements` not flattening a module-level `if` (or `try`), so a function
        defined in both branches, or in an `except`, is no definition."""
        tree = ast.parse("if X:\n    def a():\n        pass\nelse:\n    def a():\n        pass\n"
                         "try:\n    import y\nexcept ImportError:\n    def b():\n        pass\n")
        defs = _CENSUS.definitions(tree)
        assert [(d["name"], d.get("rebinds", 0)) for d in defs] == [("a", 1), ("b", 0)]

    def test_a_memo_filled_through_a_method_is_a_memo(self, repo):
        """Dies to: the memo mutators read as no call at all, so a dict filled by `.setdefault`
        has no writer and moves apart from the function that fills it."""
        _add(repo, {"espalier/cli.py": "_CACHE = {}\n\n\ndef fill():\n    _CACHE.setdefault('k', 1)\n    return _CACHE\n"})
        out = _CENSUS.census(repo, _head(repo), ["functions"])["functions"]
        assert out["memos"] == {"_CACHE": {"writers": ["fill"], "readers": ["fill"]}}


class TestTheSmallReaders:
    @pytest.mark.parametrize("path, kind", [("task-packs/TP-1.md", "records"), ("memory/x.md", "records"),
                                            ("tests/test_x.py", "tests"), ("docs/RUN.md", "docs"),
                                            ("scripts/run.py", "code")])
    def test_a_module_run_is_classed_by_where_it_lives(self, path, kind):
        """Dies to: `_run_kind` reading a record or a test as code (a pack's dated mention then
        reads as a run no move may change)."""
        assert _CENSUS._run_kind(path) == kind

    def test_a_relative_import_resolves_against_its_file_s_package(self):
        """Dies to: `_absolute` ignoring the level past one dot, so `from ..x import y` in
        espalier/sub/mod.py reads as espalier.sub.x."""
        node = ast.parse("from ..x import y\nfrom . import z\nfrom .. import w\n").body
        got = [_CENSUS._absolute("espalier/sub/mod.py", n) for n in node]
        assert got == ["espalier.x", "espalier.sub", "espalier"]

    @pytest.mark.parametrize("path, module", [("espalier/__init__.py", "espalier"), ("espalier/sub/__init__.py", "espalier.sub"),
                                              ("espalier/cli.py", "espalier.cli")])
    def test_a_package_s_init_is_the_package(self, path, module):
        """Dies to: `_module_of` keeping `.__init__`, so `from espalier import doctor` never
        matches the package's own module name."""
        assert _CENSUS._module_of(path) == module

    def test_a_top_level_import_binds_its_first_name_or_its_alias(self):
        """Dies to: `import a.b` bound to `a.b` (it binds `a`), or a module-level try's import
        left out."""
        tree = ast.parse("import os.path\nimport a.b as c\nfrom espalier import doctor, fuse as f\nfrom espalier.cli import *\n"
                         "try:\n    import simplejson\nexcept ImportError:\n    simplejson = None\n")
        assert _CENSUS.import_bindings(tree, _CENSUS.CLI, {"espalier.doctor"}) == {
            "os": "os", "c": "a.b", "doctor": "espalier.doctor", "f": "espalier", "simplejson": "simplejson"}

    def test_a_definition_s_lazy_imports_name_every_module_they_load(self):
        """Dies to: a plain `import x` inside a definition left out of its outbound edges."""
        node = ast.parse("def f():\n    import json, os.path\n    from espalier import fuse\n").body[0]
        assert _CENSUS.lazy_targets(node, _CENSUS.CLI, {"espalier.fuse"}) == [
            {"line": 2, "modules": ["json", "os.path"]}, {"line": 3, "modules": ["espalier.fuse"]}]

    def test_a_global_import_a_definition_rebinds_is_still_a_load_of_it(self):
        """Dies to: a name declared `global` read as the definition's local where it assigns it,
        so its load of cli's top-level import is no import the new module needs."""
        tree = ast.parse("from espalier._text import plural\n\n\ndef f():\n    global plural\n    plural = plural or str\n"
                         "    return plural\n")
        (d,) = _CENSUS.definitions(tree)
        assert _CENSUS._bound_loads(d, _CENSUS.import_bindings(tree, _CENSUS.CLI, set())) == {"plural"}

    def test_a_nested_definition_is_keyed_by_its_bare_name_too(self):
        """Dies to: a method keyed by `Class::method` alone, so a hand reader naming the bare
        method is reported missing."""
        spans = _CENSUS.named_spans(ast.parse("class A:\n    def m(self):\n        pass\n"))
        assert spans == {"A": [(1, 3)], "A::m": [(2, 3)], "m": [(2, 3)]}

    def test_the_bare_spelling_needs_no_dash_before_it(self):
        """Dies to: the bare spelling's lookbehind without `-`, so `my-cli.py::x` reads as a
        citation of cli.py."""
        bare = _CENSUS.citation_patterns(("espalier/cli.py",))["bare_symbol"]
        assert bare.findall("my-cli.py::x, test_cli.py::y, a/cli.py::z, a.cli.py::v and cli.py::w") == ["w"]

    @pytest.mark.parametrize("line, struck", [
        ("| 12 | ~~`DEF-1`~~ | x |", True),
        ("| ~~`DEF-1`~~ | `espalier/cli.py::a` |", True),
        ("| `DEF-1` | x |", False),
        ("   | ~~`DEF-1`~~ | x |", True),
        ("    | ~~`DEF-1`~~ | x |", False),
        ("| a long first cell | ~~`DEF-1`~~ |", False),
    ])
    def test_a_struck_row_is_read_by_the_sweep_s_own_rule(self, line, struck):
        """Dies to: the port reading the first cell alone (`[1:2]`: a row number before the id
        cell hides the strike), or an indent past three spaces read as a row."""
        sweep = {"cell_split": re.compile(r"(?<!\\)\|"), "codespan": re.compile(r"`[^`]*`"),
                 "struck_span": re.compile(r"~~`[^`]+`~~"), "row_max": 8}
        assert _CENSUS._is_struck_line(line, sweep) is struck

    def test_a_command_that_is_no_python_is_read_as_text(self):
        """Dies to: the text fallback dropped, so a probe whose command greps cli.py (no
        `python -c`) reads cli by nothing and names no symbol."""
        got = _CENSUS.probe_reads({"subject": "docs/x.md", "cmd": "grep -n cmd_alpha espalier/cli.py"},
                                  ("espalier/cli.py",), {"cmd_alpha", "_helper"})
        assert got == {"by": ["path (text)"], "symbols": ["cmd_alpha"], "parsed": False}

    def test_a_binary_file_is_left_out_and_counted(self, repo):
        """Dies to: a blob holding a NUL read as text (its citation counted), or the binary count
        left at zero, so the files read and the files counted cannot be reconciled."""
        _add(repo, _CITING)
        (repo / "docs" / "blob.bin").write_bytes(b"\x00 espalier/cli.py::_helper\n")
        _commit_all(repo, "a binary file")
        _CENSUS.source_at.cache_clear()
        out = _CENSUS.census(repo, _head(repo), ["citations"])["citations"]
        assert out["binary"] == 1
        assert out["totals"]["path_symbol"] == {"occurrences": 12, "files": 9}

    def test_a_fragment_whose_second_line_is_no_row_is_named(self, repo):
        """Dies to: a ledger fragment with no table row on line 2 (or too few cells) dropped from
        the tiers in silence, or counted as a live row."""
        _add(repo, {**_ROWS, "task-packs/ledger.d/DEF-18.md": "<!-- -->\nno table here\n",
                    "task-packs/ledger.d/DEF-19.md": "<!-- -->\n| `DEF-19` |\n"})
        out = _CENSUS.census(repo, _head(repo), ["ledger_rows"], extra={"concerns": {}})["ledger_rows"]
        assert out["not_a_row"] == ["task-packs/ledger.d/DEF-18.md", "task-packs/ledger.d/DEF-19.md"]
        assert (out["fragments"], out["live"]) == (10, 6)


class TestTheWorkingTreeIsNeverRead:
    def test_an_import_or_a_patch_only_the_working_tree_holds_is_not_counted(self, repo):
        """Dies to: the importers or the patches read from the working tree, where an uncommitted
        import and an uncommitted patch sit beside the committed ones."""
        _add(repo, {"tests/test_x.py": "from espalier import cli\n\n\ndef test_a(monkeypatch):\n"
                                       "    monkeypatch.setattr(cli, '_helper', None)\n"})
        _write(repo / "tests" / "test_x.py",
               "from espalier import cli\nfrom espalier.cli import Thing\n\n\ndef test_a(monkeypatch):\n"
               "    monkeypatch.setattr(cli, '_helper', None)\n    monkeypatch.setattr(cli, '_reader', None)\n")
        out = _CENSUS.census(repo, _head(repo), ["importers", "patches"])
        assert out["importers"]["tests"] == {"files": 1, "distinct_names": 0}
        assert (out["patches"]["sites"], sorted(out["patches"]["per_target"])) == (1, ["_helper"])

    def test_a_target_s_own_definition_is_no_loader_of_it(self, repo):
        """Dies to: a recursive function counted as a loader of itself, so a patched target whose
        only loader is its own body reads as loaded (and stays green under a move)."""
        _add(repo, {"espalier/cli.py": "def _rec(n):\n    return _rec(n - 1) if n else 0\n",
                    "tests/test_rec.py": "from espalier import cli\n\n\ndef test_r(monkeypatch):\n"
                                         "    monkeypatch.setattr(cli, '_rec', None)\n"})
        out = _CENSUS.census(repo, _head(repo), ["patches"])["patches"]
        assert out["per_target"] == {"_rec": {"sites": 1, "loaders": 0}}
        assert out["no_loader"] == ["_rec"]


class TestTheDoctorBoundaryInDepth:
    _CLI = TestTheDoctorBoundary._CLI + "\n\ndef _via_alias():\n    from espalier import doctor as d\n    return d.verdict()\n"
    _DOCTOR = '''\
def outer():
    from espalier.cli import _shared, _via_alias

    def inner():
        from espalier.cli import _probe
        return _probe()
    return _shared(), _via_alias(), inner
'''

    def test_the_innermost_holder_is_the_nested_function_and_a_lazy_alias_calls_back(self, repo):
        """Dies to: the innermost holder read as the outermost (`max` for `min`: the import in
        `inner` held by `outer`), or a cli member's lazy `from espalier import doctor as d`
        left out of the calls back into doctor."""
        _add(repo, {"espalier/cli.py": self._CLI, "espalier/doctor.py": self._DOCTOR})
        out = _CENSUS.census(repo, _head(repo), ["doctor_boundary"], extra={"concerns": {}})["doctor_boundary"]
        assert out["doctor_functions"] == ["outer"]
        assert out["doctor_functions_innermost"] == 2
        assert out["calls_back_into_doctor"]["_via_alias"] == ["verdict"]


class TestTheMannWhitneyP:
    @staticmethod
    def _by_hand(xs, ys):
        """The normal approximation written out: U by pairs, the tie-corrected variance, the
        continuity correction."""
        n1, n2 = len(xs), len(ys)
        u = sum(1.0 for x in xs for y in ys if x > y) + sum(0.5 for x in xs for y in ys if x == y)
        n = n1 + n2
        ties = sum(t ** 3 - t for t in collections.Counter([*xs, *ys]).values())
        var = n1 * n2 / 12 * ((n + 1) - ties / (n * (n - 1)))
        return 1 - statistics.NormalDist().cdf((u - n1 * n2 / 2 - 0.5) / var ** 0.5)

    @staticmethod
    def _exact(xs, ys):
        pool, n1 = [*xs, *ys], len(xs)
        def u_of(a, b):
            return sum(1.0 for x in a for y in b if x > y) + sum(0.5 for x in a for y in b if x == y)
        observed, hits, total = u_of(xs, ys), 0, 0
        for idx in itertools.combinations(range(len(pool)), n1):
            picked = set(idx)
            a = [pool[i] for i in idx]
            b = [pool[i] for i in range(len(pool)) if i not in picked]
            total += 1
            hits += u_of(a, b) >= observed
        return hits / total

    @pytest.mark.parametrize("xs, ys", [([3, 5, 8, 9, 11, 14], [1, 2, 4, 6, 7, 10]),
                                        ([0, 0, 0, 5, 6], [0, 0, 1, 2, 3, 3])], ids=["no-ties", "ties"])
    def test_the_p_is_the_tie_corrected_normal_approximation(self, xs, ys):
        """Dies to: the ranks of a tie not averaged, the tie correction dropped from the variance,
        or the continuity correction dropped: each moves the p off its written-out value."""
        got = _CENSUS.mann_whitney_greater([float(v) for v in xs], [float(v) for v in ys])
        assert got == pytest.approx(self._by_hand(xs, ys), abs=1e-12)

    def test_the_approximation_sits_near_the_exact_permutation_p(self):
        """Dies to: the one-sided direction turned round (xs above ys must read a small p, under
        0.05 here, and within 0.01 of the exact permutation p)."""
        xs, ys = [3, 5, 8, 9, 11, 14, 15], [1, 2, 4, 6, 7, 10, 12]
        got = _CENSUS.mann_whitney_greater([float(v) for v in xs], [float(v) for v in ys])
        assert got == pytest.approx(self._exact(xs, ys), abs=0.01)
        assert _CENSUS.mann_whitney_greater([float(v) for v in ys], [float(v) for v in xs]) > 0.5

    def test_an_empty_or_an_all_tied_read_has_no_p(self):
        """Dies to: a p made up where there is no variance to read one from (an empty arm, every
        value tied)."""
        assert _CENSUS.mann_whitney_greater([], [1.0]) is None
        assert _CENSUS.mann_whitney_greater([1.0, 1.0], [1.0, 1.0]) is None

    def test_both_arms_reading_zero_everywhere_is_unmeasured(self):
        """Dies to: two all-zero arms graded `not real` (no spread, so the minimum detectable ratio
        reads 1.0 and the rule calls the effect absent), where a read that saw nothing measured
        nothing; one arm of zeros beside one that read is a measurement."""
        out = _CENSUS.item3_verdict([0] * 9, [0] * 9)
        assert out["verdict"] == "unmeasured" and "zero" in out["why"]
        assert _CENSUS.item3_verdict([0] * 9, [5] * 9)["verdict"] == "not real"


class TestTheMailAtThePin:
    _MESSAGES = [{"id": "m1", "type": "note", "from": "air", "at": "2020-01-01T00:00:00Z", "re": {}, "text": "before"},
                 {"id": "m2", "type": "note", "from": "air", "at": "2020-01-02T03:04:05Z", "re": {}, "text": "at the pin"},
                 {"id": "m3", "type": "note", "from": "air", "at": "2020-01-03T00:00:00Z", "re": {}, "text": "after"}]

    @pytest.fixture
    def mailed(self, repo):
        _trunk(repo)
        _git(repo, "checkout", "-q", "-b", "mail-air")
        _write(repo / "mail.jsonl", "".join(json.dumps(m) + "\n" for m in self._MESSAGES) + "not json\n")
        _commit_all(repo, "mail")
        _git(repo, "update-ref", "refs/remotes/origin/mail/air", "HEAD")
        _git(repo, "checkout", "-q", "main")
        return repo

    def test_the_refs_are_read_by_machine(self, mailed):
        """Dies to: a mail ref keyed by its whole name, so the census looks for machine
        `refs/remotes/origin/mail/air` and finds no dispatcher's mail."""
        assert _CENSUS.mail_refs(mailed) == {"air": _git(mailed, "rev-parse", "mail-air").strip()}

    def test_a_message_after_the_pin_is_not_in_a_read_at_it(self, mailed):
        """Dies to: the mail read whole (m3, sent a day after the pin, counted at it), or cut
        before the pin's own second (m2 dropped)."""
        ctx = _ctx(mailed)
        ctx["pin"]["mail_refs"] = _CENSUS.mail_refs(mailed)
        assert [m["id"] for m in _CENSUS.mail_at(ctx)["air"]] == ["m1", "m2"]

    def test_no_mail_refs_is_unread(self, repo):
        """Dies to: a clone with no mail refs read as a record of no claims and no holds."""
        with pytest.raises(_CENSUS.Unread, match="no mail refs"):
            _CENSUS.mail_at(_ctx(repo))


class TestTheClaimIntervals:
    def test_a_released_claim_closes_and_an_open_one_runs_to_the_pin(self):
        """Dies to: every claim read as closed, or an open claim's end left at its start or empty
        rather than the pin's date (it then overlaps nothing after it)."""
        mail = {"s": [{"id": "c1", "type": "claim", "from": "s", "at": "2020-01-01T00:00:00Z",
                       "re": {"lane": "lane/a", "paths": ["espalier/cli.py"]}},
                      {"id": "r1", "type": "release", "from": "s", "at": "2020-01-01T02:00:00Z", "re": {"lane": "lane/a"}},
                      {"id": "c2", "type": "claim", "from": "s", "at": "2020-01-01T03:00:00Z",
                       "re": {"lane": "lane/b", "paths": ["docs/x.md"]}}]}
        rows = {r["id"]: r for r in _CENSUS.claim_intervals(mail, _UNTIL)}
        assert (rows["c1"]["end"], rows["c1"]["closed"], rows["c1"]["paths"]) == (
            "2020-01-01T02:00:00Z", True, ["espalier/cli.py"])
        assert (rows["c2"]["end"], rows["c2"]["closed"]) == (_UNTIL, False)


class TestTheHunkPoints:
    def test_each_hunk_shape_falls_on_its_base_lines(self):
        """Dies to: a deletion's lines not each placed, an omitted count read as zero (a change of
        one line read as an insertion), or an insertion placed on the line after it."""
        diff = "@@ -5,2 +4,0 @@\n-a\n-b\n@@ -9 +7 @@\n-c\n+d\n@@ -12,0 +11,2 @@\n+e\n+f\n"
        assert _CENSUS.hunk_points(diff) == [(5, False), (6, False), (9, False), (12, True)]


class TestTheCheckoutsOfAClone:
    def test_each_worktree_is_read_with_its_seat_and_a_gone_one_is_flagged(self, repo, tmp_path):
        """Dies to: a checkout whose directory is gone given a seat, or dropped unflagged; the
        seat not read; or the project folder derived otherwise than Claude Code names it."""
        _git(repo, "config", "espalier.machine", "air")
        side, gone = tmp_path / "side.wt", tmp_path / "gone.wt"
        _git(repo, "worktree", "add", "-q", "-b", "side", str(side))
        _git(repo, "worktree", "add", "-q", "-b", "gone", str(gone))
        os.rename(gone, tmp_path / "moved.wt")
        rows = {pathlib.Path(r["path"]).name: r for r in _CENSUS.checkouts(repo)}
        assert (rows["repo"]["seat"], rows["side.wt"]["seat"], rows["gone.wt"]["seat"]) == ("air", "air", None)
        assert (rows["side.wt"]["gone"], rows["gone.wt"]["gone"]) == (False, True)
        assert rows["side.wt"]["folder"] == re.sub(r"[^A-Za-z0-9]", "-", rows["side.wt"]["path"])

    def test_a_worktree_s_own_name_is_told_from_the_clone_s(self, repo, tmp_path):
        """Dies to: a linked worktree that inherits the clone's `espalier.machine` read as named
        in its own right (then a fork's worktree counts as the seat's checkout), a worktree named
        through `config --worktree` read as inherited, or the main checkout read as inheriting
        the name it holds."""
        _git(repo, "config", "espalier.machine", "air")
        _git(repo, "config", "extensions.worktreeConfig", "true")
        side, own = tmp_path / "side.wt", tmp_path / "own.wt"
        _git(repo, "worktree", "add", "-q", "-b", "side", str(side))
        _git(repo, "worktree", "add", "-q", "-b", "own", str(own))
        _git(own, "config", "--worktree", "espalier.machine", "air-work")
        rows = {pathlib.Path(r["path"]).name: r for r in _CENSUS.checkouts(repo)}
        assert (rows["repo"]["seat"], rows["repo"]["own_name"]) == ("air", True)
        assert (rows["side.wt"]["seat"], rows["side.wt"]["own_name"]) == ("air", False)
        assert (rows["own.wt"]["seat"], rows["own.wt"]["own_name"]) == ("air-work", True)

    def test_a_config_git_cannot_parse_is_a_failed_read_never_a_missing_name(self, repo, tmp_path):
        """Dies to: `checkouts` dropping `git config`'s exit code, so a worktree whose
        `config.worktree` git cannot parse (exit 128; rv-sib's F-bad shape) reads as one with no
        `espalier.machine`, a name never set, where its seat was never read (rv-sib F7)."""
        _git(repo, "config", "espalier.machine", "air")
        _git(repo, "config", "extensions.worktreeConfig", "true")
        bad = tmp_path / "bad.wt"
        _git(repo, "worktree", "add", "-q", "-b", "bad", str(bad))
        _git(bad, "config", "--worktree", "espalier.machine", "air-work")
        gitdir = pathlib.Path(_git(bad, "rev-parse", "--absolute-git-dir").strip())
        with (gitdir / "config.worktree").open("ab") as fh:
            fh.write('[espalier\n\tmachine = "unterminated\n'.encode("utf-8"))
        rows = {pathlib.Path(r["path"]).name: r for r in _CENSUS.checkouts(repo)}
        assert (rows["bad.wt"]["seat"], rows["bad.wt"]["own_name"]) == (None, None)
        assert rows["bad.wt"]["seat_error"].startswith("git config failed (exit 128): ")
        assert (rows["repo"]["seat"], rows["repo"]["seat_error"]) == ("air", None)

    def test_a_name_only_the_global_config_holds_is_no_worktree_s_own(self, repo, tmp_path, monkeypatch):
        """Dies to: `_own_name` taking any scope but `local` as the worktree's own (rv-sib m20), so a
        name read from the user's global config (scope `global`) makes a fork's worktree, which
        no session ran in, read as a seat's checkout."""
        glob = tmp_path / "global.gitconfig"
        _write(glob, "[espalier]\n\tmachine = air\n")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(glob))
        monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
        side = tmp_path / "side.wt"
        _git(repo, "worktree", "add", "-q", "-b", "side", str(side))
        rows = {pathlib.Path(r["path"]).name: r for r in _CENSUS.checkouts(repo)}
        assert (rows["repo"]["seat"], rows["repo"]["own_name"]) == ("air", True)
        assert (rows["side.wt"]["seat"], rows["side.wt"]["own_name"]) == ("air", False)

    def test_a_scope_git_will_not_tell_reads_none_and_a_folderless_worktree_stays_unread(self, repo, tmp_path,
                                                                                          monkeypatch):
        """Dies to: `_own_name` mapping a git failure (an old git refusing `--show-scope`, exit 129)
        to False (rv-sib m26), which turns a failed read into a worktree never named, skipped in
        silence; the section must refuse a seat's checkout with no folder instead."""
        _git(repo, "config", "espalier.machine", "air")
        side = tmp_path / "side.wt"
        _git(repo, "worktree", "add", "-q", "-b", "side", str(side))
        real = _CENSUS.git

        def git(root, *args):
            return (129, "", "error: unknown option `show-scope'") if "--show-scope" in args else real(root, *args)

        monkeypatch.setattr(_CENSUS, "git", git)
        rows = _CENSUS.checkouts(repo)
        by = {pathlib.Path(r["path"]).name: r for r in rows}
        assert (by["repo"]["own_name"], by["side.wt"]["seat"], by["side.wt"]["own_name"]) == (True, "air", None)
        main = tmp_path / "projects" / by["repo"]["folder"]
        main.mkdir(parents=True)
        _write(main / "s1.jsonl", json.dumps(_use("t1", "Read", "2020-01-01T01:00:00Z", "main",
                                                  file_path=f"{repo}/espalier/cli.py")) + "\n")
        ctx = _ctx(repo, _mail_at={}, projects_dir=str(tmp_path / "projects"), checkouts=rows)
        with pytest.raises(_CENSUS.Unread, match="transcript folder"):
            _CENSUS.section_transcripts(ctx)

    def test_a_worktree_list_git_refuses_is_unread(self, tmp_path, monkeypatch):
        """Dies to: a `git worktree list` that fails read as a clone with no checkouts, which the
        transcripts section then reads as a population of nothing."""
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
        plain = tmp_path / "plain"
        plain.mkdir()
        with pytest.raises(_CENSUS.Unread, match="git worktree list failed"):
            _CENSUS.checkouts(plain)

    def test_a_windows_path_is_compared_with_its_backslashes_as_slashes(self):
        """Dies to: a path, a cwd or a root spelled with backslashes compared as it is, so a
        Windows seat's read of cli.py maps onto no repository path."""
        assert _CENSUS._relative("C:\\work\\repo\\espalier\\cli.py", "", ["C:/work/repo"]) == "espalier/cli.py"
        assert _CENSUS._relative("espalier\\cli.py", "C:\\work\\repo", ["C:\\work\\repo"]) == "espalier/cli.py"
        assert _CENSUS.project_folder("C:\\work\\repo") == _CENSUS.project_folder("C:/work/repo") == "C--work-repo"


class TestAReadPastTheEndCountsNoLines:
    def test_a_read_whose_result_holds_no_line_counts_zero(self):
        """Dies to: `numLines` 0 falling back to the result's text, which counts a warning (three
        lines of system reminder) as three lines of cli.py read."""
        calls = _calls([_use("t1", "Read", "2020-01-01T01:00:00Z", "lane/a",
                             file_path=f"{_ROOT}/espalier/cli.py", offset=5000, limit=40),
                        _result("t1", "<system-reminder>\nWarning: the file is shorter\n</system-reminder>",
                                {"file": {"numLines": 0}})])
        assert [c["reads"] for c in calls] == [[("espalier/cli.py", 0)]]


class TestTheCensusAsACommand:
    def test_the_census_imports_at_module_level_only(self):
        """Dies to: an `import` inside a function (`import shlex` in simple_commands, which the
        module already imports; `import math` in item3_verdict), which a reader of the module's
        imports misses."""
        tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
        local = [(fn.name, s.lineno) for fn in ast.walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                 for s in ast.walk(fn) if isinstance(s, (ast.Import, ast.ImportFrom))]
        assert local == []

    def test_text_mode_says_where_it_cuts_and_prints_each_part_unread(self, repo, capsys):
        """Dies to: text mode cutting a section at 400 characters with no word that it did, or
        leaving a `<section>.<part>` unread entry out of the report, so a part read in silence
        reads as whole."""
        assert _CENSUS.main(["functions", "importers", "--at", _head(repo), "--root", str(repo)]) == 0
        out = capsys.readouterr().out
        assert "functions: {" in out and "[cut at 400 of" in out
        assert "importers.console_entry: UNREAD (pyproject.toml is not in" in out

    def test_an_unknown_section_is_refused_by_name(self, repo, capsys):
        """Dies to: an unknown section read as an empty one, or run as every section."""
        with pytest.raises(SystemExit) as exc:
            _CENSUS.main(["nonsense", "--at", _head(repo), "--root", str(repo)])
        assert exc.value.code == 2
        assert "unknown section(s) ['nonsense']" in capsys.readouterr().err

    def test_a_module_and_a_skip_reach_the_census(self, repo, capsys):
        """Dies to: `--module` not added to the CLI modules (the pin reads cli.py alone), or
        `--skip` not handed to the collision section (a skipped component then runs)."""
        _trunk(repo)
        argv = ["collision", "--at", _head(repo), "--root", str(repo), "--json", "--module", "espalier/x.py"]
        for component in ("conflicts", "pairs", "claims", "holds"):
            argv += ["--skip", component]
        assert _CENSUS.main(argv) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["pin"]["modules"] == ["espalier/cli.py", "espalier/x.py"]
        assert out["collision"]["unread"] == {k: "skipped by the caller" for k in ("conflicts", "pairs", "claims", "holds")}
        assert out["collision"]["catch_ups"]["catch_ups_in_window"] == 0


# ---------------------------------------------------------------- the second review fold

_GITLINK = "160000,1111111111111111111111111111111111111111,"


def _gitlink(repo: pathlib.Path, path: str) -> None:
    """A gitlink at `path`: tracked at the pin, never a blob, so the batch read leaves it out."""
    _git(repo, "update-index", "--add", "--cacheinfo", _GITLINK + path)
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", f"a gitlink at {path}")
    _CENSUS.source_at.cache_clear()


class TestTheMailRefsAreReadOnceAndAFailedReadIsNamed:
    @staticmethod
    def _for_each_ref(monkeypatch, answer):
        real = _CENSUS.git

        def git(root, *args):
            if args[:1] == ("for-each-ref",):
                if isinstance(answer, BaseException):
                    raise answer
                return answer
            return real(root, *args)

        monkeypatch.setattr(_CENSUS, "git", git)

    def test_a_mail_refs_read_past_its_timeout_leaves_only_the_mail_unread(self, repo, monkeypatch):
        """Dies to: the census's own `mail_refs` call, made before any section and outside
        `_section`, letting git past its timeout abort the whole run, so no section prints (rv-ab
        F1, rv-sib's Q2 note)."""
        _trunk(repo)
        self._for_each_ref(monkeypatch, subprocess.TimeoutExpired(["git", "for-each-ref"], 120.0))
        out = _CENSUS.census(repo, _head(repo), ["functions", "collision"],
                             extra={"skip_components": ("conflicts", "pairs", "holds", "catch_ups")})
        assert out["functions"]["functions"] == 6
        assert out["pin"]["mail_refs"] is None
        assert out["unread"]["pin.mail_refs"].startswith("TimeoutExpired: ")
        assert out["collision"]["claims"] is None
        assert out["collision"]["unread"]["claims"].startswith("the mail refs could not be read: TimeoutExpired: ")

    def test_a_for_each_ref_git_refuses_is_unread_never_a_clone_of_no_mail(self, repo, monkeypatch):
        """Dies to: a failed `git for-each-ref` read as a clone that holds no mail refs (`{}`), so a
        failed read is named as an absent record ("no mail refs in this clone")."""
        self._for_each_ref(monkeypatch, (128, "", "fatal: bad config line 1"))
        out = _CENSUS.census(repo, _head(repo), ["functions"])
        assert "for-each-ref" in out["unread"]["pin.mail_refs"] and "bad config" in out["unread"]["pin.mail_refs"]
        assert out["functions"]["functions"] == 6


class TestAnImporterReadInPartIsNamedWhereverItIsRead:
    @pytest.fixture
    def gitlinked(self, repo):
        _gitlink(repo, "tests/test_sub.py")
        return repo

    def test_the_clusters_read_alone_name_a_py_file_the_importers_could_not_read(self, gitlinked):
        """Dies to: `section_clusters` naming `clusters.importers` for an unparsed file only, so a
        tracked .py the batch read left out (its names may move between external, tests_only and
        dead) leaves nothing under unread when the clusters are read alone (rv-ab F2)."""
        out = _CENSUS.census(gitlinked, _head(gitlinked), ["clusters"], extra={"concerns": {}})
        assert "unread ['tests/test_sub.py']" in out["unread"]["clusters.importers"]

    def test_the_clusters_read_alone_name_an_importer_that_does_not_parse(self, repo):
        """Dies to: the clusters' unparsed-importer partial dropped (rv-ab M05): no test reached it."""
        _add(repo, {"tests/test_bad.py": "from espalier import cli\ndef f(:\n"})
        out = _CENSUS.census(repo, _head(repo), ["clusters"], extra={"concerns": {}})
        why = out["unread"]["clusters.importers"]
        assert "unparsed" in why and "tests/test_bad.py" in why

    def test_the_importers_and_the_patches_name_each_file_they_could_not_read(self, gitlinked):
        """Dies to: `importers.py_files` (rv-ab M12), `importers.module_runs` (M14) or
        `patches.tests` (M13) dropped: a tracked file the batch read left out, none of which any
        test reached."""
        out = _CENSUS.census(gitlinked, _head(gitlinked), ["importers", "patches"])
        for part in ("importers.py_files", "importers.module_runs", "patches.tests"):
            assert "tests/test_sub.py" in out["unread"][part], part


class TestTheMoveCostNamesWhatItsInputsReadInPart:
    def test_each_ingredient_over_an_unread_text_is_a_lower_bound_named_with_its_input(self, repo):
        """Dies to: `_PARTS_PRICED` leaving out the citations' and probes' `texts` (rv-ab M16), so
        their tallies over a tree with a file git could not read are priced as whole; or the census
        naming only the requested sections' partials (M68), so `citations.texts` and the rest,
        read here only as the move cost's inputs, go unnamed."""
        _add(repo, _MOVE_FILES)
        _gitlink(repo, "sub")
        out = _CENSUS.census(repo, _head(repo), ["move_cost"], extra=dict(_MOVE_EXTRA))
        for ingredient, part in (("citations", "citations.texts"), ("probes", "probes.texts"),
                                 ("symbol_keys", "readers.texts")):
            assert "lower bound" in out["unread"][f"move_cost.{ingredient}"] and part in out["unread"][f"move_cost.{ingredient}"]
            assert "['sub']" in out["unread"][part], part

    def test_a_probe_file_that_is_no_json_object_is_named(self, repo):
        """Dies to: `probes.unparsed_json` dropped (rv-ab M16b): a probe file that is no JSON, or JSON
        that is no object, read as no probe with nothing under unread."""
        _add(repo, {**_PROBES, "task-packs/probes.d/DEF-8.json": "[1]", "task-packs/probes.d/DEF-9.json": "{not json"})
        out = _CENSUS.census(repo, _head(repo), ["probes"], extra={"concerns": {}})
        assert out["probes"]["unparsed_json"] == ["task-packs/probes.d/DEF-8.json", "task-packs/probes.d/DEF-9.json"]
        assert out["unread"]["probes.unparsed_json"].startswith("2 probe file(s) are no JSON object")


class TestAPatchOfCliIsNeverDroppedUnseen:
    _BASES = '''\
from unittest.mock import patch as mpatch
from unittest import mock as um

from espalier import cli


def test_a(mocker_fixture):
    with mpatch.object(cli, "X"):
        pass
    with um.patch("espalier.cli.Y"):
        pass
    mocker_fixture.patch("espalier.cli.Z")
    um.patch.object(somewhere, "W")
'''
    _ASSIGNED = '''\
import importlib
from importlib import import_module

a = __import__("espalier.cli").cli
b = import_module("espalier.cli")
c = importlib.import_module("espalier.cli")
d = __import__("espalier.cli")


def test_x(monkeypatch):
    monkeypatch.setattr(a, "A", 1)
    monkeypatch.setattr(b, "B", 1)
    monkeypatch.setattr(c, "C", 1)
    monkeypatch.setattr(d, "D", 1)
'''
    _DECORATED = '''\
from unittest import mock

from espalier import cli


@mock.patch.object(cli, "X")
def test_a(m, cli):
    cli.Y = 1
'''

    def test_a_string_target_is_a_site_whatever_its_base_and_an_unknown_base_on_cli_unresolved(self, repo):
        """Dies to: `_PATCHER_BASES` dropping a call whose base it does not know from both the sites
        and `unresolved_owner` (rv-ab F3): `um.patch("espalier.cli.Y")` and
        `mocker_fixture.patch("espalier.cli.Z")` are patches of cli whatever the base is named, and
        `mpatch.object(cli, "X")` (an aliased `patch`) reaches cli by a patcher the census cannot
        tell is one: unresolved, never dropped. A known patcher on another module is neither."""
        _add(repo, {"tests/test_bases.py": self._BASES})
        out = _CENSUS.census(repo, _head(repo), ["patches"])["patches"]
        assert sorted(out["per_target"]) == ["Y", "Z"]
        assert out["unresolved_owner"] == {"calls": 1, "by_file": {"tests/test_bases.py": 1}}

    def test_cli_bound_by_an_assigned_import_call_is_an_alias(self, repo):
        """Dies to: `cli_aliases` reading only `x = <something>.import_module("espalier.cli")`, so cli
        bound by `__import__("espalier.cli").cli` or a bare `import_module(...)` is no alias and its
        patches are dropped unseen (rv-ab F4); `__import__("espalier.cli")` alone binds the
        package, never cli."""
        _add(repo, {"tests/test_assigned.py": self._ASSIGNED})
        assert _CENSUS.cli_aliases(ast.parse(self._ASSIGNED)) == {"a", "b", "c"}
        out = _CENSUS.census(repo, _head(repo), ["patches"])["patches"]
        assert sorted(out["per_target"]) == ["A", "B", "C"]
        assert out["unresolved_owner"] == {"calls": 0, "by_file": {}}

    def test_a_parameter_named_cli_shadows_its_function_s_body_never_its_decorators(self, repo):
        """Dies to: `_shadowed_heads` marking a function's decorators, defaults and annotations as
        inside the parameter's scope (rv-ab F5): Python evaluates `@mock.patch.object(cli, "X")`
        around the function, where `cli` is the import, so it is a site; the body's `cli.Y` is the
        parameter's, unresolved."""
        _add(repo, {"tests/test_deco.py": self._DECORATED})
        out = _CENSUS.census(repo, _head(repo), ["patches"])["patches"]
        assert sorted(out["per_target"]) == ["X"]
        assert out["unresolved_owner"] == {"calls": 1, "by_file": {"tests/test_deco.py": 1}}


class TestALocalThatShadowsAnImportIsNoLoadOfIt:
    def test_a_definition_s_bound_loads_skip_a_local_of_the_same_name(self):
        """Dies to: `_bound_loads` without its scope check (rv-ab M72), so `f`'s own local `os` reads
        as a load of cli's `import os`, an import a new module would not need."""
        tree = ast.parse("import os\nimport shutil\n\n\ndef f():\n    os = 1\n    return os, shutil.which\n")
        f = next(d for d in _CENSUS.definitions(tree) if d["name"] == "f")
        assert _CENSUS._bound_loads(f, _CENSUS.import_bindings(tree, _CENSUS.CLI, set())) == {"shutil"}


class TestTheTwoStruckCountsSayTheirRules:
    def test_the_fragments_struck_count_names_the_id_cell_rule(self, repo):
        """Dies to: `fragments.struck` (the line-2 id-cell rule) printed beside
        `split.struck.struck_fragments` (the sweep's line rule) with neither the rule text nor the
        docstring saying they count by different rules (rv-ab F7)."""
        _add(repo, _CITING)
        rule = _CENSUS.census(repo, _head(repo), ["citations"])["citations"]["rule"]
        assert "id-cell rule" in rule["fragments"] and "split.struck.struck_fragments" in rule["fragments"]
        assert "line-2 id cell" in _CENSUS.section_citations.__doc__


class TestABoxSeatWhoseTranscriptsWereNotReadIsNamed:
    @pytest.fixture
    def two_seats(self, repo, tmp_path):
        """Two CLI lanes: lane/a (#1) is air-work's and lane/b (#2) air's. Only air-work's folder
        is on disk, holding a 40-line Read of cli.py on lane/a."""
        _trunk(repo)
        _lane(repo, "lane/a", "    return 1\n", "    return 2\n")
        _land(repo, 1, "lane/a")
        _lane(repo, "lane/b", "    return _LATCH\n", "    return not _LATCH\n")
        _land(repo, 2, "lane/b")
        d = "2020-01-01T"

        def claim(mid, who, at, lane):
            return {"id": mid, "type": "claim", "from": who, "at": at, "re": {"lane": lane, "paths": ["espalier/cli.py"]}}

        def release(mid, who, at, lane):
            return {"id": mid, "type": "release", "from": who, "at": at, "re": {"lane": lane}}

        mail = {"air-work": [claim("m1", "air-work", d + "00:00:00Z", "lane/a"),
                             release("m2", "air-work", d + "02:00:00Z", "lane/a")],
                "air": [claim("m3", "air", d + "03:00:00Z", "lane/b"), release("m4", "air", d + "05:00:00Z", "lane/b")]}
        root = str(repo)
        proj = tmp_path / "projects" / "proj-work"
        proj.mkdir(parents=True)
        rec = {**_use("t1", "Read", d + "01:00:00Z", "lane/a", file_path=f"{root}/espalier/cli.py"), "cwd": root}
        _write(proj / "s1.jsonl",
               json.dumps(rec) + "\n" + json.dumps(_result("t1", "", {"file": {"numLines": 40}})) + "\n")

        def run(extra):
            ctx = _ctx(repo, _mail_at=mail, projects_dir=str(tmp_path / "projects"),
                       checkouts=[{"path": root, "seat": "air-work", "folder": "proj-work"}, *extra])
            return _CENSUS.section_transcripts(ctx), ctx
        return run

    @pytest.mark.parametrize("extra, why", [
        ([], "no checkout of this clone reads as it"),
        ([{"path": "/gone/air", "seat": None, "folder": "-gone-air", "gone": True}], "directory gone"),
        ([{"path": "/plain/air", "seat": None, "folder": "-plain-air"}], "no espalier.machine"),
    ], ids=["absent", "gone", "unnamed"])
    def test_its_lanes_are_left_out_of_both_arms_and_it_is_named(self, two_seats, extra, why):
        """Dies to: a box seat whose transcripts were never read (no checkout of it in this clone,
        its checkout gone, or no `espalier.machine`) keeping its lanes in the arms at R = 0, with
        nothing under unread and `seats` naming it (rv-c F1); `seats` is the seats read."""
        out, ctx = two_seats(extra)
        assert [(t["pr"], t["lane"], t["r"]) for t in out["treatment"]] == [(1, "lane/a", 40)]
        assert (out["lanes"], out["seats"], out["of_seats"]) == (1, ["air-work"], 4)
        assert why in out["seats_not_read"]["air"]
        assert why in ctx["_partial_unread"]["transcripts"]["seats"]

    def test_a_seat_the_mail_names_with_no_ref_here_is_named_by_the_transcripts(self, two_seats, monkeypatch):
        """Dies to: the transcripts read placing lanes by the claims of the seats whose mail refs
        this clone holds, while the mail names another seat whose claims it cannot read (Task 9's
        reasoning review, F7)."""
        real = _CENSUS.mail_at

        def mail_at(ctx):
            got = real(ctx)
            ctx["_mail_seats_missing"] = ["win"]
            return got

        monkeypatch.setattr(_CENSUS, "mail_at", mail_at)
        _out, ctx = two_seats([])
        assert "['win']" in ctx["_partial_unread"]["transcripts"]["mail_seats"]


class TestAMailSeatWhoseRefTheCloneLacksIsNamed:
    """Task 9's reasoning review, F7: a clone holding 2 of the 4 seats' mail refs read C2 and C3
    over those two, with nothing unread."""
    _NAMING = [{"id": "20200101T000000Z-air-aaaaaa", "type": "assign", "from": "air", "at": "2020-01-01T00:00:00Z",
                "re": {"seat": "win"}, "text": "a job"},
               {"id": "20200101T010000Z-air-bbbbbb", "type": "ack", "from": "air", "at": "2020-01-01T01:00:00Z",
                "re": {}, "text": "done", "ack": "20200101T003000Z-win-2-cccccc"}]
    _ALONE = [{"id": "20200101T000000Z-air-dddddd", "type": "note", "from": "air", "at": "2020-01-01T00:00:00Z",
               "re": {}, "text": "nobody else"}]

    @staticmethod
    def _mailed(repo, messages):
        _trunk(repo)
        _git(repo, "checkout", "-q", "-b", "mail-air")
        _write(repo / "mail.jsonl", "".join(json.dumps(m) + "\n" for m in messages))
        _commit_all(repo, "mail")
        _git(repo, "update-ref", "refs/remotes/origin/mail/air", "HEAD")
        _git(repo, "checkout", "-q", "main")
        return repo

    def test_each_seat_is_named_by_its_sends_an_assign_and_an_acked_id(self):
        """Dies to: an ack's id read for its machine by a split on `-`, which cuts `win-2` to
        `win`, or an assign's seat left out."""
        assert _CENSUS.mail_seats_named({"air": self._NAMING}) == {"air", "win", "win-2"}

    def test_a_named_seat_with_no_ref_is_unread_and_the_read_still_runs(self, repo):
        """Dies to: C2 and C3 computed over the seats whose refs are here, with nothing unread."""
        self._mailed(repo, self._NAMING)
        out = _CENSUS.census(repo, _head(repo), ["collision"],
                             extra={"skip_components": ("conflicts", "pairs", "holds", "catch_ups")})
        assert "['win', 'win-2']" in out["unread"]["collision.mail_seats"]
        assert out["collision"]["claims"] is not None

    def test_a_clone_holding_every_named_seat_names_nothing(self, repo):
        """Dies to: the check naming a seat whose ref is here."""
        self._mailed(repo, self._ALONE)
        out = _CENSUS.census(repo, _head(repo), ["collision"],
                             extra={"skip_components": ("conflicts", "pairs", "holds", "catch_ups")})
        assert "collision.mail_seats" not in out["unread"]
        assert out["collision"]["claims"] is not None


class TestTheSplitterReadsWhatTheShellRuns:
    @pytest.mark.parametrize("command, reads", [
        ("echo $'it\\'s' && sed -n 1,40p espalier/cli.py", [("espalier/cli.py", 80)]),
        ("sed -n 1,40p espalier/cli.py\ncat <<\\EOF\nit's here\nEOF\nsed -n 1,40p espalier/cli.py",
         [("espalier/cli.py", 40), ("espalier/cli.py", 40)]),
    ], ids=["ansi-c-quote", "bs-delim-apostrophe-body"])
    def test_a_command_the_shell_runs_is_lexed_and_its_reads_booked(self, command, reads):
        """Dies to: `shell_text` knowing no `$'...'` quote, so `\\'` closes a plain single quote and the
        lexer refuses the whole command (rv-c F2, rv-sib F5); or a `<<\\EOF` delimiter not read, so
        its body's apostrophe does the same and both reads are lost, the one before the heredoc
        included (rv-sib's downstream.py)."""
        calls = _calls([_use("t1", "Bash", "2020-01-01T01:00:00Z", "lane/a", command=command),
                        _result("t1", "", {"stdout": _lines(80)})])
        assert [c["reads"] for c in calls] == [reads]
        assert _CENSUS.lexed_commands(command) is not None

    def test_a_command_the_lexer_still_refuses_is_counted_with_its_naming(self):
        """Dies to: `calls_of` counting nowhere a command the lexer refuses (a `"` nested in `$( )`
        inside `"`, holding an apostrophe), so its reads are a silent zero."""
        misses: dict = {}
        cmd = 'echo "$(echo "it\'s")" && sed -n 1,40p espalier/cli.py'
        assert _CENSUS.lexed_commands(cmd) is None and _CENSUS.simple_commands(cmd) == []
        _CENSUS.calls_of([_use("t1", "Bash", "2020-01-01T01:00:00Z", "lane/a", command=cmd),
                          _use("t2", "Bash", "2020-01-01T01:01:00Z", "lane/a", command="echo \"it's"),
                          _use("t3", "Bash", "2020-01-01T01:02:00Z", "lane/a", command="sed -n 1p espalier/cli.py")],
                         [_ROOT], _UNTIL, lambda p: 0, misses, ["espalier/cli.py"])
        assert (misses["unlexed"], misses["unlexed_naming_cli"]) == (2, 1)

    @pytest.mark.parametrize("argv, got", [
        (["cat", "docs/a.md", "<", "espalier/cli.py"], ("read", ["docs/a.md"], None)),
        (["sed", "-n", "1p", "docs/a.md", "<espalier/cli.py"], ("read", ["docs/a.md"], 1)),
        (["cat", "-", "<", "espalier/cli.py"], ("read", ["espalier/cli.py"], None)),
        (["cat", "docs/a.md", "-", "<", "espalier/cli.py"], ("read", ["docs/a.md", "espalier/cli.py"], None)),
    ], ids=["operand-and-stdin", "sed-operand-and-stdin", "dash", "operand-and-dash"])
    def test_a_file_on_stdin_is_read_only_where_the_program_reads_its_stdin(self, argv, got):
        """Dies to: the file fed on stdin booked beside the file operands the program reads instead
        (rv-c F3): `cat`, `sed`, `head`, `tail`, `nl` and `awk` read their stdin only with no file
        operand, or a `-` among them."""
        assert _CENSUS.read_operands(argv) == got

    @pytest.mark.parametrize("command, cwd", [
        ("git show HEAD:espalier/cli.py", "/work/repo/scripts"),
        ("git -C /work/repo show HEAD:espalier/cli.py", "/tmp/elsewhere"),
        ("git -C scripts show HEAD:espalier/cli.py", "/work/repo"),
        ("git show HEAD:./cli.py", "/work/repo/espalier"),
        ("git -C /work/repo/.claude/worktrees/agent-x/scripts show HEAD:espalier/cli.py", "/"),
    ], ids=["from-a-subdirectory", "c-from-outside", "c-into-a-subdirectory", "dot-relative", "gone-worktree"])
    def test_git_show_reads_its_path_from_the_root_of_the_repository_it_runs_in(self, command, cwd):
        """Dies to: `git show REV:path` resolved against the shell's cwd (rv-c F4): git reads `path`
        from the root of the repository the command runs in (`-C dir` joined to the cwd, else the
        cwd), and from that directory only for a `./` or `../` path."""
        use = _use("t1", "Bash", "2020-01-01T01:00:00Z", "lane/a", command=command)
        use["cwd"] = cwd
        calls = _calls([use, _result("t1", "", {"stdout": _lines(40)})])
        assert [c["reads"] for c in calls] == [[("espalier/cli.py", 40)]]

    @pytest.mark.parametrize("argv, got", [
        (["head", "--lines", "50", "a"], ("read", ["a"], 50)),
        (["head", "--lines=50", "a"], ("read", ["a"], 50)),
        (["tail", "--lines=+3", "a"], ("read", ["a"], None)),
    ], ids=["lines-space", "lines-equals", "lines-from"])
    def test_head_s_long_form_count_is_read_as_its_short_form(self, argv, got):
        """Dies to: `_range` reading `--lines N` and `--lines=N` as head's default 10 (rv-c F5), so a
        piped 50-line read books 10."""
        assert _CENSUS.read_operands(argv) == got

    @pytest.mark.parametrize("error, meta", [
        (True, "Error: File content (27484 tokens) exceeds maximum allowed tokens (25000). Use offset and limit "
               "parameters to read specific portions of the file, or search for specific content instead of "
               "reading the whole file."),
        (False, "Error: File does not exist.\nNote: your current working directory is /work/repo."),
        (True, {"type": "text"}),
    ], ids=["over-the-token-limit", "string-result", "is-error"])
    def test_a_read_the_tool_refused_counts_no_line(self, error, meta):
        """Dies to: a Read whose result holds no `numLines` falling back to its text's lines, so a
        refused Read (the box's own shape: `is_error` true, `toolUseResult` the string `Error: File
        content ... exceeds maximum allowed tokens`) books its error text as lines of cli.py read
        (rv-c F6)."""
        text = meta if isinstance(meta, str) else "line one\nline two"
        res = {"type": "user", "toolUseResult": meta,
               "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": error,
                                        "content": text}]}}
        calls = _calls([_use("t1", "Read", "2020-01-01T01:00:00Z", "lane/a", file_path=f"{_ROOT}/espalier/cli.py"), res])
        assert [c["reads"] for c in calls] == [[("espalier/cli.py", 0)]]


#: Each new heredoc row (rv-sib F1 to F4, F6), the text the census keeps, and the case it is in
#: this fold's oracle run, zsh and bash agreeing with the census on every marker.
_HEREDOC_ROWS = [
    ('cat <<\\EOF\necho MK1\nEOF\necho MK2', 'cat <<\\EOF\necho MK2', "f16-bs-delim"),
    ("cat <<'END-X'\necho MK1\nEND-X\necho MK2", "cat <<'END-X'\necho MK2", "f16-sq-hyphen"),
    ("cat <<'END X'\necho MK1\nEND X\necho MK2", "cat <<'END X'\necho MK2", "f16-sq-space"),
    ('cat <<1X\necho MK1\n1X\necho MK2', 'cat <<1X\necho MK2', "f16-digit"),
    ('cat <<END-X\necho MK1\nEND-X\necho MK2', 'cat <<END-X\necho MK2', "f16-hyphen"),
    ("cat <<E'OF'\necho MK1\nEOF\necho MK2", "cat <<E'OF'\necho MK2", "f16-partial-quote"),
    ('x=1; let x<<=2; echo L$x\necho MK1\n=2\necho MK2', 'x=1; let x<<=2; echo L$x\necho MK2', "f16-let-shift"),
    ('cat <<EOF\necho MK1\n\tEOF\necho MK2\nEOF\necho MK3', 'cat <<EOF\necho MK3', "f17-plain-tab"),
    ('cat <<-EOF\necho MK1\n  EOF\necho MK2\nEOF\necho MK3', 'cat <<-EOF\necho MK3', "f17-dash-space"),
    ('cat <<EOF\necho MK1\nEOF \necho MK2\nEOF\necho MK3', 'cat <<EOF\necho MK3', "f17-trailing-space"),
    ('cat <<-EOF\n\techo MK1\n\t\tEOF\necho MK2', 'cat <<-EOF\necho MK2', "f17-dash-tab"),
    ('echo a\\\n#b; cat <<EOF\necho MK1\nEOF\necho MK2', 'echo a\\\n#b; cat <<EOF\necho MK2',
     "f15-bs-newline-midword-hash"),
    ('echo a \\\n#b; cat <<EOF\necho MK1\nEOF\necho MK2', 'echo a \\\n#b; cat <<EOF\necho MK1\nEOF\necho MK2',
     "f15-bs-newline-blank-hash"),
    ('cat <<EOF; echo "MK0\ny"\necho MK1\nEOF\ncat <<END\necho MK3\nEND\necho MK4',
     'cat <<EOF; echo "MK0\ny"\ncat <<END\necho MK4', "f15-dq-open-after-tag"),
    ('x="`cat <<EOF\necho MK1\nEOF\n`"; echo "$x"; echo MK2', 'x="`cat <<EOF\n`"; echo "$x"; echo MK2',
     "f15-backticks-in-dq"),
    ('cat <<A; x=$(cat <<B\necho MK1\nB\n)\necho MK2\nA\necho "$x"; echo MK3',
     'cat <<A; x=$(cat <<B\n)\necho "$x"; echo MK3', "f15-outer-after-sub"),
    ('cat <<EOF \\\n  ; echo MK0\necho MK1\nEOF\ncat <<END\necho MK3\nEND\necho MK4',
     'cat <<EOF \\\n  ; echo MK0\ncat <<END\necho MK4', "f18-bs-newline-after-tag"),
    (': ${x:-<<EOF}\necho MK1\nEOF\necho MK2', ': ${x:-<<EOF}\necho MK1\nEOF\necho MK2', "f18-param-default"),
    ('y=1; echo $[y<<y]\necho MK1\ny\necho MK2', 'y=1; echo $[y<<y]\necho MK1\ny\necho MK2', "f18-dollar-bracket"),
    ("cat <<\\EOF\nit's here\nEOF\ncat <<END\necho MK1\nEND\necho MK2", 'cat <<\\EOF\ncat <<END\necho MK2',
     "f9-bs-delim-apostrophe"),
    ('y=1; echo "$((y<<y))"\necho MK1\ny\necho MK2', 'y=1; echo "$((y<<y))"\necho MK1\ny\necho MK2',
     "f19-m03-arith-in-dq"),
    ("echo '<<EOF'\necho MK1\nEOF\necho MK2", "echo '<<EOF'\necho MK1\nEOF\necho MK2", "f19-m11-single-quoted"),
    ('y=1; echo $(( (y) << y ))\necho MK1\ny\necho MK2', 'y=1; echo $(( (y) << y ))\necho MK1\ny\necho MK2',
     "f19-m13-arith-paren"),
    ('x="$(echo $((1)); cat <<EOF\necho MK1\nEOF\n)"; echo "$x"; echo MK2',
     'x="$(echo $((1)); cat <<EOF\n)"; echo "$x"; echo MK2', "f19-m14-arith-in-sub-in-dq"),
]


class TestAHeredocIsReadAsTheShellsReadIt:
    @pytest.mark.parametrize("command, text", [r[:2] for r in _HEREDOC_ROWS], ids=[r[2] for r in _HEREDOC_ROWS])
    def test_the_body_starts_and_ends_where_the_shells_say(self, command, text):
        """Dies to: the delimiter read by a narrow regex (`<<\\EOF`, `<<'END X'`, `<<1X` keep their
        body; `<<END-X`, `<<E'OF'` strip every later line: rv-sib F2); a delimiter line compared
        after `.strip()` (F3); a backslash-newline's next line read as a word start, a body
        started before a quote opened on its operator's line closes, or a backquote inside `"`
        read as no context (F1); a continuation after the tag, a `${...}` or a `$[...]` read as
        opening a body (F4); or `"$((`, a single quote, arithmetic's paren depth or its `))` not
        tracked (rv-sib m03, m11, m13, m14). Each row's markers agree with zsh and bash 3.2."""
        assert _CENSUS.strip_heredocs(command) == text

    def test_a_heredoc_the_scanner_may_miss_is_flagged_and_a_read_one_is_not(self):
        """Dies to: no check of where the scanner and the old per-line regex disagree, so the
        heredocs the scanner still misses (here the named `case`-`)` inside `$(` limit, whose body
        is then read as commands) are counted nowhere (rv-sib F1's check)."""
        missed = 'x="$(case a in a) cat <<EOF\necho MK1\nEOF\n;; esac)"; echo MK2'
        assert _CENSUS.strip_heredocs(missed) == missed
        assert _CENSUS.heredoc_tag_misses(missed) == ["EOF"]
        assert _CENSUS.heredoc_tag_misses("cat <<'EOF'\nespalier/cli.py\nEOF") == []
        assert _CENSUS.heredoc_tag_misses("echo $((1 << EOF))\nsed -n 1p espalier/cli.py") == []
