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


class TestAnUnreadSectionIsNamedNeverZero:
    def test_a_section_with_no_reader_is_none_and_named(self, repo):
        """Dies to: a section the census cannot read returned as an empty dict or a zero, which
        reads as clean."""
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
