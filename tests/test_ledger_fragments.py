"""The forward ledger's rows and probes as one file each, behind one loader.

Two lanes that each file a row into one class, or strike two neighbouring
rows, edited neighbouring lines of ``task-packs/FORWARD_LEDGER.md`` and the
tail of ``task-packs/LEDGER_PROBES.json``, and GitHub's merge, which honours no
merge driver, read every such pull request as conflicting until a seat ran the
catch-up (driven 2026-10-13: two filings after one anchor conflict on the
member row, its Appendix B index row and the roster's tail; after anchors two
rows apart, on the roster's tail alone). Where ``espalier.toml`` sets
``ledger_fragments = true`` the verbs write ``task-packs/ledger.d/<id>.md`` (the
row's class, its member line and its index lines) and
``task-packs/probes.d/<id>.json`` instead, and every reader takes the loader's
in-memory view: the big file with each fragment's lines placed where the verbs
used to write them. Nothing writes the view back.
"""
from __future__ import annotations

import ast
import functools
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests import _source_segment
from tests.test_ledger_row import _args, _build_tree
from tests._live_tree import LISTING_HELPERS, checkout_rglob

# slow-exempt: each two-lane case builds a scratch repository and runs git and
# the real verbs on two branches (measured 0.2 to 0.3 s a case); what conflicts
# is git's answer, so only real git can show it.

REPO_ROOT = Path(__file__).resolve().parents[1]
CC = REPO_ROOT / "tools" / "cc"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_lf_{name}", CC / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def lr():
    return _load("ledger_row")


@pytest.fixture(scope="module")
def frag():
    return _load("_record_fragments")


@pytest.fixture(scope="module")
def gen():
    return _load("generate_ledger_regions")


@pytest.fixture(scope="module")
def chk():
    return _load("check_ledger_probes")


@pytest.fixture(autouse=True)
def _away_from_the_live_tree(tmp_path, monkeypatch):
    """A verb run without ``--root`` walks up from the working directory to
    this checkout, whose ``espalier.toml`` would then govern the fixture."""
    monkeypatch.chdir(tmp_path)


def _opt_in(root: Path) -> None:
    (root / "espalier.toml").write_text("ledger_fragments = true\n", encoding="utf-8")


def _file(lr, t, rid: str, *, after: str | None = "DEF-2") -> int:
    root = t["ledger"].parents[1]
    (root / "site").write_text("", encoding="utf-8")
    where = ["--after", after] if after else []
    return lr.main(_args(t, "--root", str(root), "file", rid, "--section", "C1", *where,
                         "--anchor", f"a/{rid}", "--text-file", str(t["body"]),
                         "--severity", "nit", "--subject", "site", "--why-not", "no local oracle"))


def _strike(lr, t, rid: str) -> int:
    root = t["ledger"].parents[1]
    (root / "site").write_text("", encoding="utf-8")
    return lr.main(_args(t, "--root", str(root), "strike", rid, "--text-file", str(t["closing"])))


class _Repo:
    """A scratch repository of the fixture tree, its verbs run on branches."""

    def __init__(self, root: Path, *, opted_in: bool) -> None:
        from tests._git_oracle import _git_env

        self.root = root
        self._env = _git_env()
        self.t = _build_tree(root)
        if opted_in:
            _opt_in(root)
        self.git("init", "-q", "-b", "main")
        for k, v in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
            self.git("config", k, v)
        self.commit("base")

    def git(self, *a: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *a], cwd=self.root, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=self._env, timeout=45)

    def commit(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    def lanes(self, lane_a, lane_b) -> subprocess.CompletedProcess:
        """Each lane runs from ``main`` on its own branch; returns GitHub's
        merge of the two (``merge-tree``, no ``.gitattributes``, no driver)."""
        for branch, verb in (("a", lane_a), ("b", lane_b)):
            self.git("switch", "-q", "-c", branch, "main")
            assert verb(self.t) == 0, f"lane {branch}'s verb refused"
            self.commit(branch)
        return self.git("merge-tree", "--write-tree", "--name-only", "--no-messages", "a", "b")

    def files_at(self, tree: str, prefix: str) -> list[tuple[str, str]]:
        names = self.git("ls-tree", "-r", "--name-only", tree, "--", prefix).stdout.split()
        return [(n.rsplit("/", 1)[-1], self.git("cat-file", "-p", f"{tree}:{n}").stdout) for n in names]

    def view_at(self, frag, tree: str) -> str:
        ledger = self.git("cat-file", "-p", f"{tree}:task-packs/FORWARD_LEDGER.md").stdout
        return frag.ledger_text_from_texts(ledger, self.files_at(tree, "task-packs/ledger.d"))


def _conflicted(merged: subprocess.CompletedProcess) -> list[str]:
    return [ln for ln in merged.stdout.splitlines()[1:] if ln.strip()]


class TestTwoLanesOnAnOptedInTree:
    """The pack's pass criterion, on the real verbs: what two lanes do to the
    records merges clean where the tree has opted in. Each was red against the
    writers that wrote the big file (0-G's hunks)."""

    def test_two_filings_after_one_anchor_merge_clean(self, lr, frag, tmp_path):
        """The worst case 0-G drove: both lanes name the same ``--after``, so
        the member rows, their index rows and the roster's tail all met. Dies
        to: a writer on an opted-in tree that still writes the big file or the
        roster."""
        repo = _Repo(tmp_path, opted_in=True)
        merged = repo.lanes(lambda t: _file(lr, t, "DEF-3"), lambda t: _file(lr, t, "DEF-4"))
        assert merged.returncode == 0, f"conflicted: {_conflicted(merged)}"
        view = repo.view_at(frag, merged.stdout.splitlines()[0])
        for rid in ("DEF-3", "DEF-4"):
            assert f"| `{rid}` | a/{rid} |" in view
            assert f"| `{rid}` | §C1 | a/{rid} |" in view

    def test_the_merged_view_equals_both_filings_in_either_order(self, lr, frag, tmp_path):
        """A row file has no position, so the view orders fragments by id and
        the result does not depend on which lane landed first. Dies to: a view
        that orders fragments by directory listing or by mtime."""
        (tmp_path / "merged").mkdir()
        repo = _Repo(tmp_path / "merged", opted_in=True)
        merged = repo.lanes(lambda t: _file(lr, t, "DEF-4"), lambda t: _file(lr, t, "DEF-3"))
        assert merged.returncode == 0, f"conflicted: {_conflicted(merged)}"
        views = [repo.view_at(frag, merged.stdout.splitlines()[0])]
        for order in (("DEF-3", "DEF-4"), ("DEF-4", "DEF-3")):
            (tmp_path / "-".join(order)).mkdir()
            seq = _build_tree(tmp_path / "-".join(order))
            _opt_in(seq["ledger"].parents[1])
            for rid in order:
                assert _file(lr, seq, rid) == 0
            views.append(frag.ledger_text(seq["ledger"].parents[1]))
        assert views[0] == views[1] == views[2]

    def test_strikes_of_two_neighbouring_fragment_rows_merge_clean(self, lr, tmp_path):
        """Two rows filed as fragments on the base, then each lane strikes one.
        In the big file they were neighbouring lines (and neighbouring index
        lines); as files they share nothing. Dies to: a strike that finds a
        fragment row and rewrites the big file instead."""
        repo = _Repo(tmp_path, opted_in=True)
        assert _file(lr, repo.t, "DEF-3") == 0
        assert _file(lr, repo.t, "DEF-4", after="DEF-3") == 0
        repo.commit("two fragment rows")
        merged = repo.lanes(lambda t: _strike(lr, t, "DEF-3"), lambda t: _strike(lr, t, "DEF-4"))
        assert merged.returncode == 0, f"conflicted: {_conflicted(merged)}"

    def test_strikes_of_two_neighbouring_legacy_rows_still_conflict(self, lr, tmp_path):
        """The negative control: the legacy rows stay in the big file until the
        fold, so two strikes of neighbouring ones still meet there. Without it a
        clean merge above could be a merge that never looks."""
        repo = _Repo(tmp_path, opted_in=True)
        merged = repo.lanes(lambda t: _strike(lr, t, "DEF-1"), lambda t: _strike(lr, t, "DEF-2"))
        assert merged.returncode == 1
        assert "task-packs/FORWARD_LEDGER.md" in _conflicted(merged)


class TestATreeThatHasNotOptedIn:
    """Off is the default and every adopter tree's state: the verbs write the
    big file and the roster as they did before row files existed."""

    def test_a_filing_writes_the_big_file_and_the_roster_and_no_fragment(self, lr, tmp_path):
        """Dies to: a writer that writes fragments without the setting."""
        t = _build_tree(tmp_path)
        assert _file(lr, t, "DEF-3") == 0
        root = t["ledger"].parents[1]
        assert "| `DEF-3` |" in t["ledger"].read_text(encoding="utf-8")
        assert [p["id"] for p in json.loads(t["probes"].read_text(encoding="utf-8"))["probes"]][-1] == "DEF-3"
        assert not (root / "task-packs" / "ledger.d").exists()
        assert not (root / "task-packs" / "probes.d").exists()


# ---------------------------------------------------------------- the loader


def _row_file(rid: str, section: str = "§C1", *, struck: bool = False, co: tuple[str, ...] = ()) -> str:
    ids = " ".join(f"`{i}`" for i in (rid, *co))
    cell = f"~~{ids}~~" if struck else ids
    member = f"| {cell} | site/{rid} | what | nit |"
    index = "\n".join(
        (f"| ~~`{i}`~~ | {section} | site/{rid} |" if struck else f"| `{i}` | {section} | site/{rid} |")
        for i in (rid, *co))
    return f"<!-- class: {section} -->\n{member}\n{index}\n"


class TestTheView:
    """``ledger_view_from_texts``: the ledger's text with each row file placed
    where the verbs used to write it, built in memory."""

    def test_no_row_files_is_the_file_itself(self, frag):
        """Dies to: a view that rewrites the file's own lines."""
        from tests.test_generate_ledger_regions import _ledger

        text = _ledger()
        assert frag.ledger_text_from_texts(text, []) == text

    def test_rows_go_after_the_class_tables_last_row_in_id_order(self, frag):
        """Dies to: dropping the legacy rows, dropping the fragments, or
        ordering fragments by the order they were handed in."""
        from tests.test_generate_ledger_regions import _ledger

        view = frag.ledger_view_from_texts(
            _ledger(), [("DEF-10.md", _row_file("DEF-10")), ("DEF-9.md", _row_file("DEF-9"))])
        assert not view.problems
        lines = view.text.split("\n")
        member = [ln.split("`")[1] for ln in lines if ln.startswith("| `DEF-") and ln.endswith(" |")
                  and " | §C1 | " not in ln]
        assert member == ["DEF-1", "DEF-2", "DEF-9", "DEF-10"]
        index = [ln.split("`")[1] for ln in lines if " | §C1 | " in ln]
        assert index == ["DEF-1", "DEF-2", "DEF-9", "DEF-10"]

    def test_the_generator_counts_a_row_file_as_a_member(self, frag):
        """The point of the view: today's grammar reads it unchanged. Dies to: a
        fragment's row placed outside its class's section."""
        from tests.test_generate_ledger_regions import _ledger, gen

        view = frag.ledger_text_from_texts(
            _ledger(), [("DEF-9.md", _row_file("DEF-9")), ("DEF-8.md", _row_file("DEF-8", struck=True))])
        assert gen.live_member_ids(view) == {"DEF-1", "DEF-2", "DEF-9"}
        assert gen.struck_member_ids(view) == {"DEF-8"}
        assert gen.appendix_b_strike_state(view)["DEF-8"] is True

    def test_a_class_with_no_rows_takes_its_first_under_the_header_rule(self, frag):
        """``ledger_row._first_row_slot``'s place. Dies to: a view that needs a
        legacy row to anchor on."""
        from tests.test_generate_ledger_regions import _ledger

        text = _ledger(c1_rows=(), appendix=())
        view = frag.ledger_view_from_texts(text, [("DEF-9.md", _row_file("DEF-9"))])
        assert not view.problems
        lines = view.text.split("\n")
        rule = lines.index("| id | site | what | sev |") + 1
        assert lines[rule + 1].startswith("| `DEF-9` |")
        assert "| `DEF-9` | §C1 | site/DEF-9 |" in lines

    def test_a_row_file_naming_a_missing_class_is_a_problem_never_dropped_silently(self, frag):
        from tests.test_generate_ledger_regions import _ledger

        view = frag.ledger_view_from_texts(_ledger(), [("DEF-9.md", _row_file("DEF-9", "§C7"))])
        assert view.problems and "§C7" in view.problems[0]
        assert "DEF-9" not in view.text

    def test_a_stray_name_is_skipped_and_said(self, frag):
        """Dies to: reading a stray file as a row."""
        from tests.test_generate_ledger_regions import _ledger

        view = frag.ledger_view_from_texts(
            _ledger(), [("README.md", _row_file("DEF-9")), ("def-9.md", _row_file("DEF-9"))])
        assert view.skipped == ["README.md", "def-9.md"] and "DEF-9" not in view.text

    @pytest.mark.parametrize("body, why", [
        ("| `DEF-9` | site | what | nit |\n", "a class line"),
        ("<!-- class: §C1 -->\n| `DEF-8` | site | what | nit |\n", "not its name"),
        ("<!-- class: §C1 -->\n| `DEF-9` | site | what | nit |\n| `DEF-9` | §C2 | site |\n",
         "not an index line"),
    ])
    def test_a_malformed_row_file_is_a_problem(self, frag, body, why):
        from tests.test_generate_ledger_regions import _ledger

        view = frag.ledger_view_from_texts(_ledger(), [("DEF-9.md", body)])
        assert any(why.split()[-1] in p for p in view.problems), view.problems

    def test_a_second_home_for_one_id_is_a_problem(self, frag):
        """A row file whose id still stands in the file's table, or two files
        carrying one id. Dies to: a view that places both."""
        from tests.test_generate_ledger_regions import _ledger

        view = frag.ledger_view_from_texts(
            _ledger(), [("DEF-2.md", _row_file("DEF-2")), ("DEF-9.md", _row_file("DEF-9", co=("DEF-2",)))])
        assert sum("DEF-2 also has a row" in p for p in view.problems) == 2

    def test_fragment_for_finds_a_co_id_row_by_either_id(self, frag, tmp_path):
        """Dies to: a lookup by file name alone."""
        ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
        (tmp_path / "task-packs" / "ledger.d").mkdir(parents=True)
        (tmp_path / "task-packs" / "ledger.d" / "DEF-9.md").write_text(
            _row_file("DEF-9", co=("LG-3",)), encoding="utf-8")
        assert frag.fragment_for(ledger, "LG-3").name == "DEF-9.md"
        assert frag.fragment_for(ledger, "DEF-9").name == "DEF-9.md"
        assert frag.fragment_for(ledger, "DEF-1") is None


class TestTheRoster:
    """``probe_roster_from_texts``: the roster file's entries, then each probe
    file's, in id order."""

    def test_probe_files_follow_the_files_entries_in_id_order(self, frag):
        roster = json.dumps({"_README": "r", "probes": [{"id": "DEF-1"}]})
        got = frag.probe_roster_from_texts(
            roster, [("DEF-10.json", json.dumps({"id": "DEF-10"})), ("DEF-9.json", json.dumps({"id": "DEF-9"}))])
        assert [p["id"] for p in got.data["probes"]] == ["DEF-1", "DEF-9", "DEF-10"]
        assert got.data["_README"] == "r" and not got.problems

    def test_no_roster_file_reads_as_an_empty_legacy_list(self, frag):
        got = frag.probe_roster_from_texts(None, [("DEF-9.json", json.dumps({"id": "DEF-9"}))])
        assert [p["id"] for p in got.data["probes"]] == ["DEF-9"]

    def test_a_probe_file_whose_id_is_not_its_name_is_a_problem(self, frag):
        got = frag.probe_roster_from_texts(
            json.dumps({"probes": []}),
            [("DEF-9.json", json.dumps({"id": "DEF-8"})), ("DEF-7.json", "{"), ("notes.json", "{}")])
        assert len(got.problems) == 3 and got.skipped == ["notes.json"] and got.data["probes"] == []
        assert any("notes.json: not a probe-file name" in p for p in got.problems)

    def test_a_second_probe_home_for_one_id_is_a_problem(self, frag):
        """Two entries for one id in the file, or a probe file for an id the
        file carries: a re-pin would stamp one and leave the other stale.
        Dies to: the roster view keeping both silently."""
        roster = json.dumps({"probes": [{"id": "DEF-1"}, {"id": "DEF-2"}, {"id": "DEF-2"}]})
        got = frag.probe_roster_from_texts(roster, [("DEF-1.json", json.dumps({"id": "DEF-1"}))])
        assert sorted(got.problems) == [
            "DEF-1.json: DEF-1 also has a probe in task-packs/LEDGER_PROBES.json -- keep one: delete this "
            "file, or the entry there",
            "task-packs/LEDGER_PROBES.json: DEF-2 has two entries -- keep one"]

    def test_a_directory_readme_is_no_stray(self, frag):
        got = frag.probe_roster_from_texts(json.dumps({"probes": []}), [("README.md", "# probes\n")])
        assert got.problems == [] and got.skipped == ["README.md"]


class TestStrayRowFiles:
    """A file beside the rows that is not a row file is named, never read as
    a row and never silent: a merge tool's ``.orig`` after the record merge
    refuses a conflict, a crashed write's ``.tmp``, a mis-cased id."""

    @pytest.mark.parametrize("name", ["DEF-12.md.orig", "DEF-12.md.tmp", "Def-12.md"])
    def test_a_stray_name_is_a_problem(self, frag, name):
        """Dies to: a skipped name read as nothing."""
        from tests.test_generate_ledger_regions import _ledger

        view = frag.ledger_view_from_texts(_ledger(), [(name, _row_file("DEF-12"))])
        assert any(p.startswith(f"{name}: not a row-file name") for p in view.problems), view.problems

    def test_a_readme_beside_the_rows_is_no_stray(self, frag):
        from tests.test_generate_ledger_regions import _ledger

        assert frag.ledger_view_from_texts(_ledger(), [("README.md", "# rows\n")]).problems == []

    def test_a_byte_order_mark_is_not_part_of_the_class_line(self, frag, tmp_path):
        """An editor's BOM: the row file still parses. Dies to: a strict read
        that keeps the mark in front of the class line."""
        root = _fragment_tree(tmp_path)
        (root / "task-packs" / "ledger.d" / "DEF-9.md").write_bytes(b"\xef\xbb\xbf" + _row_file("DEF-9").encode())
        view = frag.ledger_view_at(root / "task-packs" / "FORWARD_LEDGER.md")
        assert not view.problems and "| `DEF-9` | site/DEF-9 |" in view.text

    def test_a_roster_file_that_is_not_json_raises_as_before(self, frag):
        with pytest.raises(ValueError):
            frag.probe_roster_from_texts("{", [])


class TestTheSetting:
    """``ledger_fragments`` reads like ``changelog_fragments``: one scan."""

    @pytest.mark.parametrize("toml, on", [
        ("ledger_fragments = true\n", True),
        ("ledger_fragments = false\n", False),
        ("ledger_fragments = \"true\"\n", False),
        ("[table]\nledger_fragments = true\n", False),
        ("changelog_fragments = true\n", False),
        ("", False),
    ])
    def test_only_a_top_level_bare_true_turns_it_on(self, frag, tmp_path, toml, on):
        (tmp_path / "espalier.toml").write_text(toml, encoding="utf-8")
        assert frag.ledger_fragments_setting(tmp_path)[0] is on


class TestTheGrammarCopies:
    """The loader imports no sibling, so it carries copies of the generator's
    grammar; each is pinned to its one home."""

    def test_each_copy_equals_the_generators(self, frag):
        from tests.test_generate_ledger_regions import gen

        assert frag._SECTION_HEADING_RE.pattern == gen._SECTION_HEADING.pattern
        assert frag._MEMBER_ROW_RE.pattern == gen._MEMBER_ROW.pattern
        assert frag._APPENDIX_B_ROW_RE.pattern == gen._APPENDIX_B_ROW.pattern
        assert frag._ID_SHAPE_RE.pattern == gen._ID_SHAPE.pattern

    @pytest.mark.parametrize("row", [
        "| `DEF-1` | site | what | nit |",
        "| `DEF-539` `LG-6` | site | what | nit |",
        "| ~~`DEF-3`~~ | site | x \\| y | nit |",
        "| `cc/GOAL.md` `DEF-4` | site |",
        "| not a row |",
    ])
    def test_row_ids_agrees_with_cell_ids(self, frag, row):
        from tests.test_generate_ledger_regions import gen

        assert frag.row_ids(row) == gen.cell_ids(row)


class TestTheLedgerVerb:
    """``_record_fragments.py ledger``: the view for a person, never written."""

    def test_it_prints_the_view_and_names_what_it_could_not_place(self, frag, tmp_path, capsys):
        """Dies to: a verb that prints the file alone, or that writes the view
        into it."""
        from tests.test_generate_ledger_regions import _ledger

        packs = tmp_path / "task-packs"
        (packs / "ledger.d").mkdir(parents=True)
        (packs / "FORWARD_LEDGER.md").write_text(_ledger(), encoding="utf-8")
        (packs / "ledger.d" / "DEF-9.md").write_text(_row_file("DEF-9"), encoding="utf-8")
        assert frag.main(["--root", str(tmp_path), "ledger"]) == 0
        assert "| `DEF-9` | site/DEF-9 |" in capsys.readouterr().out
        assert "DEF-9" not in (packs / "FORWARD_LEDGER.md").read_text(encoding="utf-8")
        (packs / "ledger.d" / "DEF-7.md").write_text(_row_file("DEF-7", "§C7"), encoding="utf-8")
        assert frag.main(["--root", str(tmp_path), "ledger"]) == 1
        assert "not placed: DEF-7.md" in capsys.readouterr().err


def _fragment_tree(root: Path, *, rows: dict[str, str] | None = None,
                   probes: dict[str, dict] | None = None, ledger: str | None = None) -> Path:
    """A scratch root with the fixture ledger, a two-entry roster, and the
    given row and probe files."""
    from tests.test_generate_ledger_regions import _ledger

    packs = root / "task-packs"
    (packs / "ledger.d").mkdir(parents=True)
    (packs / "probes.d").mkdir()
    (packs / "FORWARD_LEDGER.md").write_text(ledger if ledger is not None else _ledger(), encoding="utf-8")
    (packs / "LEDGER_PROBES.json").write_text(json.dumps(
        {"probes": [{"id": "DEF-1", "subject": "s"}, {"id": "DEF-2", "subject": "s"}]}, indent=1) + "\n",
        encoding="utf-8")
    for name, body in (rows or {}).items():
        (packs / "ledger.d" / name).write_text(body, encoding="utf-8")
    for name, entry in (probes or {}).items():
        (packs / "probes.d" / name).write_text(json.dumps(entry, indent=1) + "\n", encoding="utf-8")
    return root


class TestTheGeneratorReadsTheView:
    """``generate_ledger_regions.py`` checks the view and repairs the file."""

    def test_check_counts_a_row_file_and_prints_it(self, gen, tmp_path, capsys):
        root = _fragment_tree(tmp_path, rows={"DEF-9.md": _row_file("DEF-9")},
                              probes={"DEF-9.json": {"id": "DEF-9", "subject": "s"}})
        assert gen.main(["--root", str(root), "--check"]) == 0
        assert "converged (3 live rows)" in capsys.readouterr().out
        assert gen.main(["--root", str(root), "--print"]) == 0
        assert "§C1: 3" in capsys.readouterr().out

    def test_a_struck_row_files_probe_file_is_drift(self, gen, tmp_path, capsys):
        """The probe-roster region reads the probe files too. Dies to: a
        generator that reads the roster file alone."""
        root = _fragment_tree(tmp_path, rows={"DEF-9.md": _row_file("DEF-9", struck=True)},
                              probes={"DEF-9.json": {"id": "DEF-9", "subject": "s"}})
        assert gen.main(["--root", str(root), "--check"]) == 1
        assert "DEF-9: struck in its class section but still carries a probe" in capsys.readouterr().out

    def test_a_row_file_the_view_cannot_place_fails_the_check(self, gen, tmp_path, capsys):
        root = _fragment_tree(tmp_path, rows={"DEF-9.md": _row_file("DEF-9", "§C7")})
        assert gen.main(["--root", str(root), "--check"]) == 1
        assert "[row-files] DEF-9.md: class §C7 has no section" in capsys.readouterr().out

    def test_the_floors_read_the_view(self, gen, tmp_path):
        """A ledger whose rows are files declares floors its own text cannot
        meet. Dies to: floors counted on the file's text."""
        from tests.test_generate_ledger_regions import _ledger

        text = _ledger().replace("## §2 ", "<!-- ledger-floors: sections=1 rows=3 -->\n\n## §2 ", 1)
        root = _fragment_tree(tmp_path, rows={"DEF-9.md": _row_file("DEF-9")}, ledger=text,
                              probes={"DEF-9.json": {"id": "DEF-9", "subject": "s"}})
        assert gen.main(["--root", str(root), "--check"]) == 0

    def test_write_repairs_the_file_and_never_writes_the_view(self, gen, tmp_path):
        """A stored total is removed from the file's own text; the row file's
        lines stay out of it. Dies to: ``--write`` writing the view."""
        from tests.test_generate_ledger_regions import STORED_ALL, _ledger

        root = _fragment_tree(tmp_path, rows={"DEF-9.md": _row_file("DEF-9")}, ledger=_ledger(stored=STORED_ALL),
                              probes={"DEF-9.json": {"id": "DEF-9", "subject": "s"}})
        gen.main(["--root", str(root), "--write"])
        after = (root / "task-packs" / "FORWARD_LEDGER.md").read_text(encoding="utf-8")
        assert "DEF-9" not in after and not gen.stored_counts(after)


# ---------------------------------------------------------------- the writers


def _bytes(t) -> tuple[bytes, bytes]:
    return t["ledger"].read_bytes(), t["probes"].read_bytes()


def _opted_in_tree(tmp_path: Path) -> dict:
    t = _build_tree(tmp_path)
    _opt_in(tmp_path)
    return t


class TestTheWritersOnAnOptedInTree:
    """Where ``ledger_fragments = true``, a filing writes a row file and a
    probe file, and a strike or re-pin edits the row where it lives."""

    def test_a_filing_writes_two_files_and_neither_record(self, lr, tmp_path, capsys):
        """Dies to: a writer on an opted-in tree that writes the big file or the
        roster."""
        t = _opted_in_tree(tmp_path)
        before = _bytes(t)
        assert _file(lr, t, "DEF-3") == 0
        assert _bytes(t) == before
        packs = tmp_path / "task-packs"
        row = (packs / "ledger.d" / "DEF-3.md").read_text(encoding="utf-8")
        assert row.splitlines() == ["<!-- class: §C1 -->",
                                    "| `DEF-3` | a/DEF-3 | **A new defect.** Who: an adopter. | nit |",
                                    "| `DEF-3` | §C1 | a/DEF-3 |"]
        entry = json.loads((packs / "probes.d" / "DEF-3.json").read_text(encoding="utf-8"))
        assert entry["id"] == "DEF-3" and entry["why_not"] == "no local oracle"
        assert "--after DEF-2 places nothing here" in capsys.readouterr().err

    def test_a_crlf_ledger_is_left_byte_for_byte(self, lr, tmp_path):
        """An adopter's tree does not inherit our `.gitattributes` eol=lf, so a
        Windows checkout holds the ledger CRLF. The tree above is CRLF only on
        Windows, which no required cell runs; this one is CRLF on every OS.
        Dies to: a skip-unchanged compare that reads line ends as a change."""
        t = _opted_in_tree(tmp_path)
        lf = t["ledger"].read_bytes().replace(b"\r\n", b"\n")
        t["ledger"].write_bytes(lf.replace(b"\n", b"\r\n"))
        before = _bytes(t)
        assert _file(lr, t, "DEF-3") == 0
        assert _bytes(t) == before
        assert (tmp_path / "task-packs" / "ledger.d" / "DEF-3.md").is_file()

    def test_a_strike_rewrites_the_row_file_and_retires_its_probe_file(self, lr, tmp_path):
        """Dies to: a strike that looks for a row file's row in the big file."""
        t = _opted_in_tree(tmp_path)
        assert _file(lr, t, "DEF-3") == 0
        before = _bytes(t)
        assert _strike(lr, t, "DEF-3") == 0
        assert _bytes(t) == before
        packs = tmp_path / "task-packs"
        row = (packs / "ledger.d" / "DEF-3.md").read_text(encoding="utf-8").splitlines()
        assert row[1].startswith("| ~~`DEF-3`~~ |") and "CLOSED 2026-09-06" in row[1]
        assert row[2] == "| ~~`DEF-3`~~ | §C1 | a/DEF-3 |"
        assert not (packs / "probes.d" / "DEF-3.json").exists()

    def test_a_co_id_row_file_is_struck_by_its_second_id(self, lr, frag, tmp_path):
        """Dies to: a lookup by file name alone."""
        t = _opted_in_tree(tmp_path)
        packs = tmp_path / "task-packs"
        (packs / "ledger.d").mkdir()
        (packs / "ledger.d" / "DEF-9.md").write_text(_row_file("DEF-9", co=("LG-3",)), encoding="utf-8")
        assert _strike(lr, t, "LG-3") == 0
        row = (packs / "ledger.d" / "DEF-9.md").read_text(encoding="utf-8").splitlines()
        assert row[1].startswith("| ~~`DEF-9`~~ ~~`LG-3`~~ |")
        assert row[2:] == ["| ~~`DEF-9`~~ | §C1 | site/DEF-9 |", "| ~~`LG-3`~~ | §C1 | site/DEF-9 |"]

    def test_a_repin_rewrites_the_probe_file_and_neither_record(self, lr, tmp_path):
        t = _opted_in_tree(tmp_path)
        assert _file(lr, t, "DEF-3") == 0
        before = _bytes(t)
        root = str(t["ledger"].parents[1])
        assert lr.main(_args(t, "--root", root, "repin", "DEF-3", "--anchor", "b/DEF-3",
                             "--reason", "the site moved")) == 0
        assert _bytes(t) == before
        packs = tmp_path / "task-packs"
        row = (packs / "ledger.d" / "DEF-3.md").read_text(encoding="utf-8").splitlines()
        assert "| b/DEF-3 |" in row[1] and row[2] == "| `DEF-3` | §C1 | b/DEF-3 |"
        entry = json.loads((packs / "probes.d" / "DEF-3.json").read_text(encoding="utf-8"))
        assert "the site moved" in entry["verified_2026_09_06"]

    def test_an_orphan_probe_file_is_a_second_home_and_refused(self, lr, tmp_path, capsys):
        """A probe file whose row is gone: filing over it would replace it
        unseen. Dies to: a filing that writes over a file already there."""
        t = _opted_in_tree(tmp_path)
        (tmp_path / "task-packs" / "probes.d").mkdir()
        orphan = tmp_path / "task-packs" / "probes.d" / "DEF-3.json"
        orphan.write_text(json.dumps({"id": "DEF-3", "subject": "kept"}) + "\n", encoding="utf-8")
        assert _file(lr, t, "DEF-3") == 2
        assert "a second home for one id" in capsys.readouterr().err
        assert json.loads(orphan.read_text(encoding="utf-8"))["subject"] == "kept"

    def test_a_first_filing_creates_no_roster_file(self, lr, tmp_path):
        """A tree with no live row and no roster: the filing's probe is a
        file, so the roster stays absent. Dies to: a writer that writes the
        roster whether or not it changed."""
        from tests.test_generate_ledger_regions import _ledger

        t = _opted_in_tree(tmp_path)
        t["ledger"].write_text(_ledger(c1_rows=(), appendix=()), encoding="utf-8")
        t["probes"].unlink()
        assert _file(lr, t, "DEF-3", after=None) == 0
        assert not t["probes"].exists()
        assert (tmp_path / "task-packs" / "probes.d" / "DEF-3.json").is_file()

    def test_a_row_file_id_is_taken_for_minting(self, lr, tmp_path):
        """An id that lives only as a file is not free. Dies to: minting from
        the two files' text alone."""
        t = _opted_in_tree(tmp_path)
        (tmp_path / "task-packs" / "ledger.d").mkdir()
        (tmp_path / "task-packs" / "ledger.d" / "DEF-1199.md").write_text(
            _row_file("DEF-1199", co=("DEF-1200",)), encoding="utf-8")
        taken = lr.taken_numbers(tmp_path, "DEF", ledger=t["ledger"], probes=t["probes"])
        assert {1199, 1200} <= taken


class TestTheWritersRefuseAndSayWhatTheyMeet:
    """What the 2026-10-13 reviews drove: a second probe home on either path,
    the order the files are written in, a malformed setting, an --after row
    that lives in a file, a row file that does not parse."""

    def test_an_orphan_probe_file_refuses_a_filing_into_the_file_too(self, lr, tmp_path, capsys):
        """Setting off: the row goes into the file, and a probe file for the id
        already sits beside the roster. Dies to: the second-home check on the
        opted-in path only."""
        t = _build_tree(tmp_path)
        (tmp_path / "task-packs" / "probes.d").mkdir()
        (tmp_path / "task-packs" / "probes.d" / "DEF-3.json").write_text(
            json.dumps({"id": "DEF-3", "subject": "kept"}) + "\n", encoding="utf-8")
        before = _bytes(t)
        assert _file(lr, t, "DEF-3") == 2
        assert "a second home for one id" in capsys.readouterr().err and _bytes(t) == before

    def test_row_files_are_written_before_probe_files(self, lr, tmp_path, monkeypatch):
        """A crash between the two leaves a live row with no probe (the probe
        runner names it), never an orphan probe file nobody names. Dies to:
        probe files written first."""
        t = _opted_in_tree(tmp_path)
        gen = lr._load("generate_ledger_regions")
        written: list[str] = []
        real = gen._atomic_write

        def record(path, text):
            written.append(path.parent.name)
            return real(path, text)

        monkeypatch.setattr(gen, "_atomic_write", record)
        monkeypatch.setattr(lr, "_load", lambda name: gen if name == "generate_ledger_regions" else lr._load(name))
        assert _file(lr, t, "DEF-3") == 0
        assert written == ["ledger.d", "probes.d"], written

    def test_a_setting_written_but_not_read_as_on_is_said(self, lr, tmp_path, capsys):
        """``= True`` reads as off: the filing goes into the file, and says so.
        Dies to: the reason dropped."""
        t = _build_tree(tmp_path)
        (tmp_path / "espalier.toml").write_text("ledger_fragments = True\n", encoding="utf-8")
        assert _file(lr, t, "DEF-3") == 0
        err = capsys.readouterr().err
        assert "neither true nor false" in err and "this row goes into FORWARD_LEDGER.md" in err

    def test_an_after_row_that_lives_in_a_file_is_named_when_the_setting_is_off(self, lr, tmp_path, capsys):
        t = _build_tree(tmp_path)
        rows = tmp_path / "task-packs" / "ledger.d"
        rows.mkdir()
        (rows / "DEF-9.md").write_text(_row_file("DEF-9"), encoding="utf-8")
        assert _file(lr, t, "DEF-3", after="DEF-9") == 2
        assert "its row lives in ledger.d/DEF-9.md" in capsys.readouterr().err

    @pytest.mark.parametrize("verb, said", [("strike", "nothing struck"), ("repin", "nothing re-pinned")])
    def test_a_row_file_that_does_not_parse_is_named_never_reported_missing(self, lr, tmp_path, capsys, verb, said):
        """Dies to: a broken row file read as no row at all, by either verb
        that finds a row by its id."""
        t = _opted_in_tree(tmp_path)
        rows = tmp_path / "task-packs" / "ledger.d"
        rows.mkdir()
        (rows / "DEF-9.md").write_text("| `DEF-9` | no class line | nit |\n", encoding="utf-8")
        before = _bytes(t)
        if verb == "strike":
            assert _strike(lr, t, "DEF-9") == 2
        else:
            assert lr.main(_args(t, "--root", str(t["ledger"].parents[1]), "repin", "DEF-9",
                                 "--anchor", "b/DEF-9", "--reason", "the site moved")) == 2
        err = capsys.readouterr().err
        assert "ledger_row: DEF-9.md: " in err and f"repair the row file first, {said}" in err, err
        assert _bytes(t) == before


class TestTheChecksNameEveryStrayAndEverySecondHome:
    """The generator's --check, and a verb's convergence, report what the views
    could not read: a stray name, a corrupt probe file, a second probe home."""

    def test_check_reports_a_stray_name_and_a_corrupt_probe_file(self, gen, tmp_path, capsys):
        """Dies to: the roster's problems or the ledger view's stray names left
        out of the drift (both reviews: a corrupt probe file converged)."""
        root = _fragment_tree(tmp_path, rows={"DEF-12.md.orig": _row_file("DEF-12")})
        (root / "task-packs" / "probes.d" / "DEF-1.json").write_text("{not json", encoding="utf-8")
        assert gen.main(["--root", str(root), "--check"]) == 1
        out = capsys.readouterr().out
        assert "DEF-12.md.orig: not a row-file name" in out and "DEF-1.json: not JSON" in out

    def test_a_pending_second_probe_home_does_not_converge(self, lr, tmp_path):
        """Dies to: convergence reading the pending roster's ids without its
        problems."""
        t = _opted_in_tree(tmp_path)
        pending = lr._Pending(t["ledger"], t["probes"])
        pending.probe_files[tmp_path / "task-packs" / "probes.d" / "DEF-1.json"] = {"id": "DEF-1"}
        gen = lr._load("generate_ledger_regions")
        _text, drift = lr._converge(gen, t["ledger"].read_text(encoding="utf-8"), t["probes"], pending)
        assert any("DEF-1 also has a probe in" in d["detail"] for d in drift), drift


class TestTheOnboardingGateSeesTheRowFiles:
    """``cli._ledger_is_the_untouched_seed``: an adopter who opted in before its
    first filing keeps the seed file untouched while its rows are files."""

    @pytest.mark.contract
    def test_a_row_file_beside_the_seed_means_it_has_been_filed_into(self, tmp_path):
        """Dies to: the gate reading the seed file alone (every upgrade then
        re-ran the onboarding filings and called them failed)."""
        from espalier import cli
        from espalier.managed_inventory import seed_stamp_line

        body = (REPO_ROOT / "espalier" / "assets" / "seed" / "FORWARD_LEDGER.md").read_text(encoding="utf-8")  # ledger-read: the adopter's seed, one file by design
        ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
        ledger.parent.mkdir(parents=True)
        ledger.write_text(seed_stamp_line(body) + body, encoding="utf-8")
        assert cli._ledger_is_the_untouched_seed(ledger) is True
        (ledger.parent / "ledger.d").mkdir()
        for name in ("README.md", "CLAUDE.md", ".DEF-1.md.swp"):   # never a row (never_a_record)
            (ledger.parent / "ledger.d" / name).write_text("x\n", encoding="utf-8")
        assert cli._ledger_is_the_untouched_seed(ledger) is True
        (ledger.parent / "ledger.d" / "DEF-1.md").write_text(_row_file("DEF-1"), encoding="utf-8")
        assert cli._ledger_is_the_untouched_seed(ledger) is False


class TestDroppingsAreNeverRecords:
    """``never_a_record``: what an operating system or an editor leaves in any
    directory it opens is skipped without a word; any other name that is not a
    record's is still a stray, named with its repair (round-2 reviews: one
    Finder visit stopped every verb on the box)."""

    @pytest.mark.parametrize("name", [".DS_Store", "._DEF-1.md", ".DEF-1.md.swp", ".gitkeep", "DEF-1.md~",
                                      "#DEF-1.md#", "Thumbs.db", "desktop.ini", "CLAUDE.md", "readme.md"])
    def test_a_dropping_is_no_problem_beside_the_rows_or_the_probes(self, frag, name):
        """Dies to: the predicate left out of either view."""
        from tests.test_generate_ledger_regions import _ledger

        assert frag.ledger_view_from_texts(_ledger(), [(name, "x")]).problems == []
        assert frag.probe_roster_from_texts(json.dumps({"probes": []}), [(name, "x")]).problems == []

    @pytest.mark.parametrize("name", ["DEF-12.md.orig", "DEF-12.md.tmp", "Def-12.md", "notes.md", "DEF-12.json"])
    def test_any_other_name_is_a_stray_and_the_problem_says_the_repair(self, frag, name):
        """Dies to: a predicate wide enough to hide a mis-cased row or a
        crashed write's only copy."""
        from tests.test_generate_ledger_regions import _ledger

        problems = frag.ledger_view_from_texts(_ledger(), [(name, _row_file("DEF-12"))]).problems
        assert len(problems) == 1 and "rename it to <id>.md" in problems[0] and "delete it" in problems[0]

    def test_a_byte_order_mark_from_a_blob_is_not_part_of_the_record(self, frag):
        """A trend reader decodes a blob as plain UTF-8, mark and all. Dies to:
        the mark stripped on a file read only."""
        from tests.test_generate_ledger_regions import _ledger

        bom = chr(0xFEFF)
        view = frag.ledger_view_from_texts(_ledger(), [("DEF-9.md", bom + _row_file("DEF-9"))])
        assert view.problems == [] and "site/DEF-9" in view.text
        roster = frag.probe_roster_from_texts(json.dumps({"probes": []}),
                                              [("DEF-9.json", bom + json.dumps({"id": "DEF-9"}))])
        assert roster.problems == [] and [p["id"] for p in roster.data["probes"]] == ["DEF-9"]


class TestAVerbRefusesOnlyWhatItWorsens:
    """``ledger_row._scope_drift``: a verb refuses on a problem its own write
    introduces or one about a row it touches; one the tree already carried
    about other rows is a note, and ``--check`` and CI hold the tree to it
    (operator, 2026-10-13)."""

    def test_an_unrelated_stray_is_noted_and_the_filing_lands(self, lr, gen, tmp_path, capsys):
        """Dies to: convergence refusing on every problem the tree carries."""
        t = _opted_in_tree(tmp_path)
        rows = tmp_path / "task-packs" / "ledger.d"
        rows.mkdir()
        (rows / "DEF-12.md.orig").write_text("a backup\n", encoding="utf-8")
        assert _file(lr, t, "DEF-3") == 0
        err = capsys.readouterr().err
        assert "note -- the tree already carries 1 problem(s)" in err and "DEF-12.md.orig" in err, err
        assert (rows / "DEF-3.md").is_file()
        assert gen.main(["--root", str(tmp_path), "--check"]) == 1

    def test_a_held_problem_about_the_row_it_touches_still_refuses(self, lr, tmp_path, capsys):
        """A second roster entry for DEF-2: a re-pin of DEF-2 would stamp one
        and leave the other. Dies to: the touched-id rule dropped."""
        t = _opted_in_tree(tmp_path)
        data = json.loads(t["probes"].read_text(encoding="utf-8"))
        data["probes"].append(dict(data["probes"][1]))
        t["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        (tmp_path / "site").write_text("", encoding="utf-8")  # the probes' subject
        before = _bytes(t)
        root = str(t["ledger"].parents[1])
        assert lr.main(_args(t, "--root", root, "repin", "DEF-2", "--anchor", "b/DEF-2",
                             "--reason", "the site moved")) == 2
        assert "DEF-2 has two entries" in capsys.readouterr().err and _bytes(t) == before
        assert _file(lr, t, "DEF-3") == 0
        assert "DEF-2 has two entries" in capsys.readouterr().err

    def test_a_co_id_rows_second_id_is_touched_too(self, lr, tmp_path):
        """A held problem naming LG-3 is about the row a strike of DEF-9
        rewrites when the two share a row. Dies to: touched ids read from the
        file names alone."""
        t = _opted_in_tree(tmp_path)
        pending = lr._Pending(t["ledger"], t["probes"], ("DEF-9",))
        pending.rows[tmp_path / "task-packs" / "ledger.d" / "DEF-9.md"] = _row_file("DEF-9", struck=True, co=("LG-3",))
        pending.probe_files[tmp_path / "task-packs" / "probes.d" / "DEF-9.json"] = None
        assert pending.touched() == {"DEF-9", "LG-3"}

    def test_a_copy_of_a_held_problem_is_new_and_a_moved_line_is_not(self, lr):
        """Dies to: a set (a second copy slips through) or a key that keeps the
        line number (a held problem below an inserted row reads as new)."""
        a = {"region": "row-files", "detail": "x.orig: a stray"}
        assert lr._scope_drift([a, dict(a)], [a], set()) == ([a], [a])
        assert lr._scope_drift([a], None, set()) == ([a], [])
        moved = {"region": "appendix-b", "detail": "line 9: DEF-5 is missing", "line": 9}
        held = {"region": "appendix-b", "detail": "line 7: DEF-5 is missing", "line": 7}
        assert lr._scope_drift([moved], [held], {"DEF-50"}) == ([], [moved])
        assert lr._scope_drift([moved], [held], {"DEF-5"}) == ([moved], [])
        fifty = {"region": "r", "detail": "DEF-50: x"}
        assert lr._scope_drift([fifty], [fifty], {"DEF-5"}) == ([], [fifty])


class TestTheRoundThreeEdges:
    """The narrow round-3 review of the refusal change (2026-10-13), and the
    operator's call that followed it: a verb notes what it did not cause only
    where the tree keeps rows as files."""

    def test_a_tree_that_has_not_opted_in_refuses_on_every_problem(self, lr, tmp_path, capsys):
        """No gate holds an adopter's ledger, so the verbs stay the hold there.
        Dies to: the scoping applied to every tree."""
        t = _build_tree(tmp_path)
        data = json.loads(t["probes"].read_text(encoding="utf-8"))
        data["probes"].append(dict(data["probes"][1]))
        t["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        before = _bytes(t)
        assert _file(lr, t, "DEF-3") == 2
        err = capsys.readouterr().err
        assert "DEF-2 has two entries" in err and "each new with this write" not in err and _bytes(t) == before

    def test_readers_and_verbs_read_a_marked_roster_alike(self, lr, frag, tmp_path):
        """A byte-order mark on the roster (PowerShell 5.1's UTF8): the readers
        and the verbs both refuse it, so CI says what every verb would. Dies to:
        a reader that drops the mark while the verbs keep it (round 3: CI green,
        every verb a traceback)."""
        t = _opted_in_tree(tmp_path)
        t["probes"].write_bytes(b"\xef\xbb\xbf" + t["probes"].read_bytes())
        with pytest.raises(ValueError):
            frag.probe_roster_at(t["probes"])
        with pytest.raises(ValueError):
            lr._load_probes(t["probes"], ledger_text=t["ledger"].read_text(encoding="utf-8"))

    def test_a_count_in_a_held_problem_is_not_a_new_problem(self, lr):
        """A strike lowers a class's live-row count, which an off-vocabulary
        tag's problem names. Dies to: the count kept in the key."""
        held = {"region": "vocabulary", "detail": "§C9: class-index Population 'X' is not one of ('A',) "
                                                  "or MIXED, and the class has 3 live row(s)"}
        now = dict(held, detail=held["detail"].replace("3 live", "2 live"))
        assert lr._scope_drift([now], [held], {"DEF-1"}) == ([], [now])

    def test_a_mis_cased_name_is_about_the_id_it_spells(self, lr):
        """Dies to: a case-sensitive touched-id match (a mis-cased row file
        beside the row a verb writes is noted, not refused)."""
        stray = {"region": "row-files", "detail": "Def-12.md: not a row-file name (<id>.md)"}
        assert lr._scope_drift([stray], [stray], {"DEF-12"}) == ([stray], [])

    def test_a_missing_appendix_b_is_named_per_row_file(self, frag):
        """Dies to: one problem for every row file (a filing's own unplaced
        index line read as about rows it does not touch)."""
        from tests.test_generate_ledger_regions import _ledger

        text = _ledger().split("## Appendix B")[0]
        view = frag.ledger_view_from_texts(text, [("DEF-8.md", _row_file("DEF-8")), ("DEF-9.md", _row_file("DEF-9"))])
        assert sorted(p.split(":", 1)[0] for p in view.problems if "Appendix B" in p) == ["DEF-8.md", "DEF-9.md"]

    def test_an_entry_with_no_id_is_a_problem_and_never_a_crash(self, lr, frag, tmp_path, capsys):
        """Dies to: the roster view passing an id-less entry, or a strike that
        looks every entry up by key (round 3: a KeyError on every strike)."""
        got = frag.probe_roster_from_texts(json.dumps({"probes": [{"subject": "s"}]}), [])
        assert got.problems == ["task-packs/LEDGER_PROBES.json: an entry carries no id -- give it its row's "
                                "id, or delete it"]
        t = _opted_in_tree(tmp_path)
        data = json.loads(t["probes"].read_text(encoding="utf-8"))
        data["probes"].append({"subject": "site"})
        t["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        assert _strike(lr, t, "DEF-1") == 0
        assert "an entry carries no id" in capsys.readouterr().err

    def test_a_legacy_co_id_repin_touches_both_ids(self, lr, tmp_path, capsys):
        """DEF-2's row in the file carries LG-5, whose index row the re-pin
        moves; a second roster entry for LG-5 is about that row. Dies to: the
        re-pin's touched ids read from row files alone (round 3, driven)."""
        t = _opted_in_tree(tmp_path)
        text = t["ledger"].read_text(encoding="utf-8")
        text = text.replace("| `DEF-2` | site | what | minor |", "| `DEF-2` `LG-5` | site | what | minor |")
        text = text.replace("| `DEF-2` | §C1 | site |", "| `DEF-2` | §C1 | site |\n| `LG-5` | §C1 | site |")
        t["ledger"].write_text(text, encoding="utf-8")
        data = json.loads(t["probes"].read_text(encoding="utf-8"))
        data["probes"] += [dict(id="LG-5", subject="site", why_not="x"), dict(id="LG-5", subject="site", why_not="x")]
        t["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        (tmp_path / "site").write_text("", encoding="utf-8")
        before = _bytes(t)
        assert lr.main(_args(t, "--root", str(tmp_path), "repin", "DEF-2", "--anchor", "moved/DEF-2",
                             "--open-value", "b", "--reason", "the site moved")) == 2
        assert "LG-5 has two entries" in capsys.readouterr().err and _bytes(t) == before

    def test_the_probe_runner_notes_a_stray_and_runs(self, chk, tmp_path, capsys):
        """Dies to: every roster problem refusing the advisory run (a gitignored
        .orig beside the probe files stopped it whole)."""
        root = _fragment_tree(tmp_path)
        (root / "task-packs" / "probes.d" / "DEF-1.json.orig").write_text("{}", encoding="utf-8")
        chk.main(["--root", str(root)])
        out = capsys.readouterr().out
        assert "NOTE: DEF-1.json.orig: not a probe-file name" in out and "refusing to report" not in out

    def test_a_crashed_writes_tmp_beside_the_rows_says_run_the_verb_again(self, frag):
        from tests.test_generate_ledger_regions import _ledger

        problems = frag.ledger_view_from_texts(_ledger(), [("DEF-3.md.tmp", _row_file("DEF-3"))]).problems
        assert "a crashed write's .tmp: delete it and run the verb again" in problems[0]


class TestAStrikeRetiresItsProbeFirst:
    """A strike that dies part-way leaves a live row with no probe -- a note,
    and a re-run completes it -- never a struck row still carrying a probe,
    which no verb could clear (round-2 review, driven)."""

    @staticmethod
    def _dies_writing(lr, monkeypatch, at) -> object:
        real_load = lr._load
        gen = real_load("generate_ledger_regions")
        real_write = gen._atomic_write

        def write(path, text):
            if at(path):
                raise OSError(28, "No space left on device")
            return real_write(path, text)

        monkeypatch.setattr(gen, "_atomic_write", write)
        monkeypatch.setattr(lr, "_load", lambda name: gen if name == "generate_ledger_regions" else real_load(name))
        return lambda: monkeypatch.setattr(gen, "_atomic_write", real_write)

    @staticmethod
    def _dies(call) -> bool:
        try:
            return call() != 0
        except OSError:
            return True

    def test_a_strike_that_dies_at_the_row_file_runs_again(self, lr, tmp_path, monkeypatch):
        """Dies to: the struck row written before the probe file is removed."""
        t = _opted_in_tree(tmp_path)
        assert _file(lr, t, "DEF-3") == 0
        packs = tmp_path / "task-packs"
        heal = self._dies_writing(lr, monkeypatch, lambda p: p.parent.name == "ledger.d")
        assert self._dies(lambda: _strike(lr, t, "DEF-3"))
        assert not (packs / "probes.d" / "DEF-3.json").exists()
        assert "~~" not in (packs / "ledger.d" / "DEF-3.md").read_text(encoding="utf-8")
        heal()
        assert _strike(lr, t, "DEF-3") == 0
        assert "~~`DEF-3`~~" in (packs / "ledger.d" / "DEF-3.md").read_text(encoding="utf-8")

    def test_a_strike_in_the_file_that_dies_at_the_ledger_runs_again(self, lr, tmp_path, monkeypatch):
        """The legacy form: the roster's entry goes before the ledger's row.
        Dies to: the ledger written before the roster."""
        t = _build_tree(tmp_path)
        heal = self._dies_writing(lr, monkeypatch, lambda p: p.name == "FORWARD_LEDGER.md")
        assert self._dies(lambda: _strike(lr, t, "DEF-1"))
        assert "DEF-1" not in {p["id"] for p in json.loads(t["probes"].read_text(encoding="utf-8"))["probes"]}
        assert "~~`DEF-1`~~" not in t["ledger"].read_text(encoding="utf-8")
        heal()
        assert _strike(lr, t, "DEF-1") == 0
        assert "~~`DEF-1`~~" in t["ledger"].read_text(encoding="utf-8")


class TestTheProbesVerb:
    """``_record_fragments.py probes``: the roster as its readers see it, the
    one spelling an instruction gives for reading every probe."""

    def test_it_prints_the_file_and_the_probe_files_as_one_roster(self, frag, tmp_path, capsys):
        root = _fragment_tree(tmp_path, probes={"DEF-9.json": {"id": "DEF-9", "why_not": "none"}})
        assert frag.main(["--root", str(root), "probes"]) == 0
        assert [p["id"] for p in json.loads(capsys.readouterr().out)["probes"]] == ["DEF-1", "DEF-2", "DEF-9"]

    def test_a_problem_is_named_and_exits_one(self, frag, tmp_path, capsys):
        root = _fragment_tree(tmp_path, probes={"DEF-1.json": {"id": "DEF-1"}})
        assert frag.main(["--root", str(root), "probes"]) == 1
        assert "(not read: DEF-1.json: DEF-1 also has a probe in" in capsys.readouterr().err


class TestTheMergeHoldsTheRosterToo:
    """``record_merge.regenerate_ledger``: a merge that leaves a second probe
    for one id stops every ledger verb that touches it, so it is no merge to
    commit, and the refusal names the file, never 'at line None'."""

    def test_a_merged_second_probe_home_is_unresolvable_and_named(self, gen, tmp_path):
        """Dies to: the roster's problems left out of the merge's check."""
        rm = _load("record_merge")
        root = _fragment_tree(tmp_path, probes={"DEF-1.json": {"id": "DEF-1"}})
        packs = root / "task-packs"
        with pytest.raises(rm.Unresolvable) as caught:
            rm.regenerate_ledger((packs / "FORWARD_LEDGER.md").read_text(encoding="utf-8"), gen,
                                 packs / "LEDGER_PROBES.json")
        message = str(caught.value)
        assert "[row-files] DEF-1.json: DEF-1 also has a probe in" in message and "line None" not in message


class TestTheSettingNoteNamesEachMisreading:
    """``file_row``'s note keys on three phrases of the setting reader's; each
    must reach the operator. Dies to: a phrase the reader no longer says."""

    @pytest.mark.parametrize("toml, phrase", [
        ("ledger_fragments = True\n", "neither true nor false"),
        ("[harness]\nledger_fragments = true\n", "not the top-level setting"),
    ])
    def test_a_setting_written_but_not_read_as_on_is_said(self, lr, tmp_path, capsys, toml, phrase):
        t = _build_tree(tmp_path)
        (tmp_path / "espalier.toml").write_text(toml, encoding="utf-8")
        assert _file(lr, t, "DEF-3") == 0
        err = capsys.readouterr().err
        assert phrase in err and "this row goes into FORWARD_LEDGER.md" in err, err

    def test_an_unreadable_setting_file_is_said(self, lr, tmp_path, capsys):
        t = _build_tree(tmp_path)
        (tmp_path / "espalier.toml").mkdir()
        assert _file(lr, t, "DEF-3") == 0
        err = capsys.readouterr().err
        assert "could not be read" in err and "this row goes into FORWARD_LEDGER.md" in err, err


@pytest.mark.contract
class TestTheRowFilesAreCheckedOutLf:
    """``.gitattributes`` pins the row and probe files to LF, as the verbs
    write them. Dies to: either line dropped (git's own answer, not a grep)."""

    def test_git_reads_lf_for_both_directories(self):
        out = subprocess.run(["git", "-C", str(REPO_ROOT), "check-attr", "eol", "--",
                              "task-packs/ledger.d/DEF-1.md", "task-packs/probes.d/DEF-1.json"],
                             capture_output=True, text=True, encoding="utf-8", check=True).stdout.splitlines()
        assert out == ["task-packs/ledger.d/DEF-1.md: eol: lf", "task-packs/probes.d/DEF-1.json: eol: lf"]


class TestRowFilesOnATreeThatHasNotOptedIn:
    """A tree that turned the setting off keeps reading its row files; a new
    filing goes into the big file, and nothing writes a row file's lines there."""

    def test_a_filing_lands_in_the_file_and_the_row_file_stays_out_of_it(self, lr, frag, tmp_path):
        """Dies to: a legacy write placed by the view's positions, or the view
        written back."""
        t = _build_tree(tmp_path)
        packs = tmp_path / "task-packs"
        (packs / "ledger.d").mkdir()
        (packs / "ledger.d" / "DEF-9.md").write_text(_row_file("DEF-9"), encoding="utf-8")
        (packs / "probes.d").mkdir()
        (packs / "probes.d" / "DEF-9.json").write_text(json.dumps({"id": "DEF-9", "subject": "s"}) + "\n",
                                                        encoding="utf-8")
        assert _file(lr, t, "DEF-3") == 0
        text = t["ledger"].read_text(encoding="utf-8")
        assert "| `DEF-3` |" in text and "DEF-9" not in text
        assert not (packs / "ledger.d" / "DEF-3.md").exists()
        view = frag.ledger_text(tmp_path)
        assert view.index("| `DEF-3` |") < view.index("| `DEF-9` |")

    def test_a_legacy_filing_lands_right_after_its_anchor_when_a_row_file_sits_above_it(
            self, lr, tmp_path):
        """The view's positions and the file's disagree below a row file's
        class: a row file in §C1 puts one more line above every §C2 row. The
        filing into §C2 must land directly after its anchor in the FILE. Dies
        to: slots taken from the view."""
        from tests.test_generate_ledger_regions import _ledger

        t = _build_tree(tmp_path)
        t["ledger"].write_text(_ledger(mixed=True), encoding="utf-8")
        packs = tmp_path / "task-packs"
        (packs / "ledger.d").mkdir()
        (packs / "ledger.d" / "DEF-9.md").write_text(_row_file("DEF-9"), encoding="utf-8")
        (packs / "probes.d").mkdir()
        (packs / "probes.d" / "DEF-9.json").write_text(json.dumps({"id": "DEF-9", "subject": "s"}) + "\n",
                                                        encoding="utf-8")
        data = json.loads(t["probes"].read_text(encoding="utf-8"))
        data["probes"].append({"id": "DEF-3", "subject": "site", "cmd": None, "open_value": None,
                               "why_not": "fixture"})
        t["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        (tmp_path / "site").write_text("", encoding="utf-8")
        assert lr.main(_args(t, "--root", str(tmp_path), "file", "DEF-4", "--section", "C2", "--after", "DEF-3",
                             "--anchor", "a/DEF-4", "--text-file", str(t["body"]), "--severity", "nit",
                             "--subject", "site", "--why-not", "no local oracle",
                             "--population", "HYGIENE", "--audience", "MAINTAINER")) == 0
        lines = t["ledger"].read_text(encoding="utf-8").split("\n")
        anchor = next(i for i, ln in enumerate(lines) if ln.startswith("| `DEF-3` | site |"))
        assert lines[anchor + 1].startswith("| `DEF-4` | a/DEF-4 |")
        index = next(i for i, ln in enumerate(lines) if ln.startswith("| `DEF-3` | §C2 |"))
        assert lines[index + 1] == "| `DEF-4` | §C2 | a/DEF-4 |"


class TestTheFilesAreTrackedAndShip:
    """A row or probe file the verbs write is tracked by git and ships with the
    ledger. Both ``.gitignore`` blocks re-include by name under
    ``task-packs/*``, so without the two directory lines every file was
    silently untracked while ``file`` reported success (measured 2026-10-13)."""

    _SHAPES = ("task-packs/ledger.d/DEF-9.md", "task-packs/probes.d/DEF-9.json")

    @staticmethod
    def _ignored(repo: Path, rel: str) -> bool:
        from tests._git_oracle import _git_env

        return subprocess.run(["git", "check-ignore", "-q", "--no-index", rel], cwd=repo,
                              env=_git_env(), timeout=45).returncode == 0

    def test_the_block_init_writes_tracks_them(self, tmp_path):
        """Dies to: a directory dropped from ``GITIGNORE_REINCLUDES``."""
        from espalier import cli
        from tests._git_oracle import _git_env

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, env=_git_env(), check=True, timeout=45)
        (tmp_path / ".gitignore").write_text(
            "\n".join(cli.render_gitignore_entries(cli.REQUIRED_GITIGNORE)) + "\n", encoding="utf-8")
        assert self._ignored(tmp_path, "task-packs/TP-1-draft.md")   # the rule is live
        for rel in self._SHAPES:
            assert not self._ignored(tmp_path, rel), rel

    def test_this_repositorys_gitignore_tracks_them(self, tmp_path):
        """The self-host block is its own allow-list (its hand copy is the
        QUICKSTART's). Dies to: the two lines dropped from ``.gitignore``."""
        from tests._git_oracle import _git_env

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, env=_git_env(), check=True, timeout=45)
        (tmp_path / ".gitignore").write_bytes((REPO_ROOT / ".gitignore").read_bytes())
        assert self._ignored(tmp_path, "task-packs/scratch-note.md")   # the allow-list is live
        for rel in self._SHAPES:
            assert not self._ignored(tmp_path, rel), rel

    def test_they_ship_with_the_ledger(self):
        """Dies to: the directories missing from the ship set."""
        from espalier.surface_contract import classify_release_path, is_local_only

        for rel in self._SHAPES:
            assert not is_local_only(rel) and classify_release_path(rel) == "public", rel
        assert is_local_only("task-packs/ledger.d/nested/DEF-9.md")


# ---------------------------------------------------------------- the reader census

_CENSUS_ROOTS = ("tools/cc", "scripts", "espalier", "tests")
#: The records by name: the two files and the two directories.
_RECORD_NAMES = ("FORWARD_LEDGER.md", "LEDGER_PROBES.json", "ledger.d", "probes.d")
_VERB_MODULES = ("ledger_row", "generate_ledger_regions", "check_ledger_probes", "record_merge")
#: An expression that names a ledger record (a path, a constant such as
#: ``_LEDGER`` or ``PROBES``, a variable named for one), never a module's own
#: source file (``check_ledger_probes.py``).
_RECORD_EXPR_RE = re.compile(r"(?i)ledger|probes")
_MODULE_SOURCE_RE = re.compile(r"\.py\b")
#: In a test, only a read of the LIVE tree is a reader; a scratch fixture is
#: read for what a verb wrote to it.
_LIVE_TREE_RE = re.compile(r"REPO_ROOT|\b_ROOT\b|parents\[|gen\._LEDGER|gen\._PROBES|\b_LEDGER\b|\b_PROBE_FILE\b")
#: The loader's functions, and the two pending-view methods a writer converges
#: against. A read is credited only when its own value flows into one of these.
_LOADER_CALLS = frozenset({
    "ledger_view_at", "probe_roster_at", "ledger_text_from_texts", "ledger_view_from_texts",
    "probe_roster_from_texts",
})
_PENDING_CALLS = frozenset({"view", "probe_ids", "roster"})
_LEDGER_READ = "# ledger-read:"
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@functools.lru_cache(maxsize=8)
def _lines(text: str) -> tuple[str, ...]:
    """``text`` split once through the shared slicer (``tests/_source_segment.py``):
    the stdlib call re-splits the whole file on every call, a per-character loop
    on Python 3.10, and this census timed out on the 3.10 cell alone
    (2026-10-13, `DEF-762`'s mechanism)."""
    return _source_segment.source_lines(text)


def _src(text: str, node: ast.AST) -> str:
    return _source_segment.segment(_lines(text), node) or ""


def _names_a_record(text: str, node: ast.AST) -> bool:
    s = _src(text, node)
    return bool(_RECORD_EXPR_RE.search(s)) and not _MODULE_SOURCE_RE.search(s)


def _is_loader_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Name):
        return f.id in _LOADER_CALLS
    if isinstance(f, ast.Attribute):
        if f.attr in _LOADER_CALLS:
            return True
        return f.attr in _PENDING_CALLS and isinstance(f.value, ast.Name) and f.value.id == "pending"
    return False


#: A child process that reads the file it is handed, as its argv's first word.
_READING_COMMANDS = frozenset({"grep", "rg", "cat", "head", "tail", "sed", "awk", "wc"})
#: A module that imports a constant named for a record (``board.LEDGER``,
#: ``cli._LEDGER_REL``) reads through it while naming no record literal.
_IMPORTS_A_RECORD_NAME_RE = re.compile(r"^\s*from\s+\S+\s+import\s+[^\n]*(?i:ledger|probes)", re.M)


def _read_target(text: str, node: ast.Call) -> "ast.AST | None":
    """The expression a call reads, when it reads a file or a commit: a path's
    ``read_text``/``read_bytes``/``open``, ``open(p)``, ``json.load(s)(x)``, a
    git ``show``/``cat-file`` (its whole call), or a child process whose argv
    opens with a reading command (``grep``, ``cat``: its whole call)."""
    f = node.func
    if isinstance(f, ast.Attribute) and f.attr in ("read_text", "read_bytes", "open"):
        return f.value
    if isinstance(f, ast.Name) and f.id == "open" and node.args:
        return node.args[0]
    if isinstance(f, ast.Attribute) and f.attr in ("load", "loads") and node.args \
            and not isinstance(node.args[0], ast.Call):
        return node.args[0]
    if node.args and isinstance(node.args[0], (ast.List, ast.Tuple)) and node.args[0].elts \
            and isinstance(node.args[0].elts[0], ast.Constant) and node.args[0].elts[0].value in _READING_COMMANDS:
        return node
    for arg in node.args:
        for sub in ast.walk(arg):
            if isinstance(sub, ast.Constant) and sub.value in ("show", "cat-file"):
                return node
    return None


def _globs_a_record(text: str, node: ast.Call, bound: "dict[str, ast.AST]") -> bool:
    """A ``glob``/``rglob`` over the task-pack folder whose pattern takes in
    the ledger or its roster: every file it yields is read as one of many,
    the record among them, with no name saying so. The folder is the method's
    receiver, or the first argument of one of ``tests/_live_tree.py``'s
    ``LISTING_HELPERS``, the form DEF-2013 routes every tests/ walk to (the
    two that take no pattern fall out at the pattern check)."""
    import fnmatch

    f = node.func
    if isinstance(f, ast.Attribute) and f.attr in ("glob", "rglob"):
        folder, args = f.value, node.args
    elif isinstance(f, ast.Name) and f.id in LISTING_HELPERS and node.args:
        folder, args = node.args[0], node.args[1:]
    else:
        return False
    if not (args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str)):
        return False
    pattern = args[0].value
    if not any(fnmatch.fnmatch(name, pattern) for name in ("FORWARD_LEDGER.md", "LEDGER_PROBES.json")):
        return False
    receiver = [folder] + ([bound[folder.id]] if isinstance(folder, ast.Name) and folder.id in bound else [])
    # The folder itself, never a folder under it (task-packs/Done holds packs).
    return any(re.search(r"""["']task-packs/?["']\)?\s*$""", _src(text, e)) for e in receiver)


def _record_reads(rel: str, text: str, tree: ast.AST) -> list[tuple[int, str, str, bool]]:
    """``(line, scope name, target, credited)`` for every read of a ledger record
    in a module that names a record or loads a verb module. A read is of a
    record when its target names one, or is a name (or a class's ``self.X``)
    bound in its scope from an expression that names one. It is credited when
    its own value flows into a loader call: nested in one, or assigned to a
    name a loader call in the same scope then takes."""
    names_record = any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                       and any(r in n.value for r in (*_RECORD_NAMES, *_VERB_MODULES, "task-packs"))
                       for n in ast.walk(tree))
    imports_verb = any(isinstance(n, (ast.Import, ast.ImportFrom)) and any(
        v in (getattr(n, "module", "") or "") or any(v in a.name for a in n.names) for v in _VERB_MODULES)
        for n in ast.walk(tree))
    imports_record_name = any(isinstance(n, ast.ImportFrom) and any(
        _RECORD_EXPR_RE.search(a.asname or a.name) for a in n.names) for n in ast.walk(tree))
    if not (names_record or imports_verb or imports_record_name):
        return []
    parents: dict[ast.AST, ast.AST] = {}
    for p in ast.walk(tree):
        for c in ast.iter_child_nodes(p):
            parents[c] = p

    def scope_of(node: ast.AST) -> ast.AST:
        cur = parents.get(node)
        while cur is not None and not isinstance(cur, (*_SCOPES, ast.Module)):
            cur = parents.get(cur)
        return cur if cur is not None else tree

    bound_by_scope: dict[ast.AST, dict[str, ast.AST]] = {}

    def bindings(scope: ast.AST) -> dict[str, ast.AST]:
        """Names bound in ``scope``'s own body (not nested scopes), by the value.
        Walked once per scope: every call in a scope asks for the same one."""
        if scope in bound_by_scope:
            return bound_by_scope[scope]
        out: dict[str, ast.AST] = {}
        stack = list(ast.iter_child_nodes(scope))
        while stack:
            n = stack.pop()
            if isinstance(n, _SCOPES):
                continue
            if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    if isinstance(t, ast.Name):
                        out[t.id] = n.value
            stack.extend(ast.iter_child_nodes(n))
        bound_by_scope[scope] = out
        return out

    def credited_at(node: ast.AST, scope: ast.AST) -> bool:
        """Whether a read's own value flows into a loader call: nested in one,
        or assigned to a name a loader call in the same scope takes."""
        cur = parents.get(node)
        while cur is not None and cur is not scope:
            if _is_loader_call(cur):
                return True
            if isinstance(cur, (ast.Assign, ast.AnnAssign)):
                names = {t.id for t in (cur.targets if isinstance(cur, ast.Assign) else [cur.target])
                         if isinstance(t, ast.Name)}
                return any(_is_loader_call(call) and any(
                    isinstance(n, ast.Name) and n.id in names
                    for a in (*call.args, *[k.value for k in call.keywords]) for n in ast.walk(a))
                    for call in ast.walk(scope))
            cur = parents.get(cur)
        return False

    # A reading helper: a module-level function that reads one of its own
    # parameters without handing the text to the loader. A call that passes it
    # a record is a read at the call (one hop; a helper calling a helper is the
    # ledger row's, not this census's).
    # A read in the helper that names its reason explains every call to it.
    helpers: dict[str, dict[str, int]] = {}
    source_lines = text.splitlines()
    for fn in getattr(tree, "body", []):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs)]
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and scope_of(node) is fn:
                target = _read_target(text, node)
                if (isinstance(target, ast.Name) and target.id in params and not credited_at(node, fn)
                        and _LEDGER_READ not in source_lines[node.lineno - 1]):
                    helpers.setdefault(fn.name, {})[target.id] = params.index(target.id)

    def targets_of(node: ast.Call) -> list[ast.AST]:
        found = [t] if (t := _read_target(text, node)) is not None else []
        if isinstance(node.func, ast.Name) and node.func.id in helpers:
            for name, i in helpers[node.func.id].items():
                arg = node.args[i] if i < len(node.args) else next(
                    (k.value for k in node.keywords if k.arg == name), None)
                if arg is not None:
                    found.append(arg)
        return found

    module_bound = bindings(tree)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        scope = scope_of(node)
        local = bindings(scope)
        name = getattr(scope, "name", "<module>")
        if _globs_a_record(text, node, {**module_bound, **local}):
            out.append((node.lineno, name, _src(text, node)[:70], False))
            continue
        cur = scope
        while cur is not None and not isinstance(cur, ast.ClassDef):
            cur = parents.get(cur)
        class_bound = bindings(cur) if cur is not None else {}
        for target in targets_of(node):
            bound_expr = None
            if isinstance(target, ast.Name):
                bound_expr = local.get(target.id) or module_bound.get(target.id)
            elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                    and target.value.id in ("self", "cls"):
                bound_expr = class_bound.get(target.attr)
            evidence = [target] + ([bound_expr] if bound_expr is not None else [])
            if not any(_names_a_record(text, e) for e in evidence):
                continue
            if rel.startswith("tests/") and not any(_LIVE_TREE_RE.search(_src(text, e)) for e in evidence):
                continue
            out.append((node.lineno, name, _src(text, target)[:70], credited_at(node, scope)))
    return out


def _unexplained_reads(root: Path) -> list[str]:
    """Every read of a ledger record under the census roots that is neither
    credited (its value flows into the loader) nor explained (its line names a
    reason). The loader is the one module that reads the files themselves."""
    found = []
    for base in _CENSUS_ROOTS:
        for p in checkout_rglob(root / base, "*.py"):
            rel = p.relative_to(root).as_posix()
            if "/_vendor/" in rel or "/assets/" in rel or rel == "tools/cc/_record_fragments.py":
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            if not (any(name in text for name in (*_RECORD_NAMES, *_VERB_MODULES, "task-packs"))
                    or _IMPORTS_A_RECORD_NAME_RE.search(text)):
                continue   # a cheap pre-filter: the AST arm below asks the same of constants and imports
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            lines = text.splitlines()
            for line, scope, src, credited in _record_reads(rel, text, tree):
                if credited or _LEDGER_READ in lines[line - 1]:
                    continue
                found.append(f"{rel}:{line} {scope}: {src}")
    return found


class TestTheReaderCensus:
    """Every reader of the ledger or its roster reads the loader's view, or
    names why it reads the file itself. A reader that reads the file alone
    does not red when a row moves into a file: it reads less and passes, which
    is the blocker the parent pack's own sweep found (a ship check that read
    one file and refused every handoff). Derived by AST over tools/cc, scripts,
    espalier and the tests that read the live tree.

    What it decides: a direct read (a path, a name or ``self.X`` bound to
    one, ``open``, ``json.load``, a git ``show``), a read through a one-hop
    helper that reads its own parameter, a child process that greps or cats a
    record, a glob over the task-pack folder that takes a record in, and a
    read through a path constant imported from another module. What it does
    not: a helper calling a helper, a path passed through two calls, and a
    credited read whose raw text is also used elsewhere -- ``DEF-4018``, by
    the operator's call (2026-10-13). Its silence means no reader of those
    shapes, never no reader."""

    @pytest.mark.contract
    def test_every_reader_takes_the_view_or_names_its_reason(self):
        found = _unexplained_reads(REPO_ROOT)
        assert not found, (
            "readers of the ledger or its roster that neither reach the loader "
            "(tools/cc/_record_fragments.py's ledger_view_at / probe_roster_at) nor carry "
            f"`{_LEDGER_READ} <why>` on the line:\n  " + "\n  ".join(found))

    @pytest.mark.contract
    def test_every_reason_says_something(self):
        bare = []
        for base in _CENSUS_ROOTS:
            for p in checkout_rglob(REPO_ROOT / base, "*.py"):
                rel = p.relative_to(REPO_ROOT).as_posix()
                if "/_vendor/" in rel or rel == "tests/test_ledger_fragments.py":
                    continue
                for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if _LEDGER_READ in line and not line.split(_LEDGER_READ, 1)[1].strip():
                        bare.append(f"{rel}:{n}")
        assert not bare, f"`{_LEDGER_READ}` with no reason: {bare}"

    @pytest.mark.contract
    def test_the_census_sees_a_planted_reader_and_reads_the_exits(self, tmp_path):
        """One planted reader per shape the first census let through (both
        reviews, 2026-10-13). Dies to: a census blind to a new module, to the
        live-tree arm in tests, to a path held in a variable or a class
        attribute, to `.open()` or a git `show`, to a module that only imports
        a verb, that credits a whole function for one view call, or that takes
        a helper's name or docstring as the view."""
        cc = tmp_path / "tools" / "cc"
        cc.mkdir(parents=True)
        (cc / "planted.py").write_text(
            "import subprocess\n"
            "from pathlib import Path\n"
            "def rows():\n"
            "    return Path('task-packs/FORWARD_LEDGER.md').read_text()\n"
            "def kept():\n"
            "    return Path('task-packs/FORWARD_LEDGER.md').read_text()  # ledger-read: a reason\n"
            "def viewed(rf):\n"
            "    t = Path('task-packs/FORWARD_LEDGER.md').read_text()\n"
            "    return rf.ledger_view_at(Path('x'), ledger_text=t)\n"
            "def _ledger_view():\n"
            "    '''Named for the view, and its docstring names record_fragments.'''\n"
            "    return Path('task-packs/FORWARD_LEDGER.md').read_text()\n"
            "def held():\n"
            "    p = Path('task-packs') / 'LEDGER_PROBES.json'\n"
            "    return p.read_text()\n"
            "def opened():\n"
            "    with Path('task-packs/FORWARD_LEDGER.md').open() as fh:\n"
            "        return fh.read()\n"
            "def shown():\n"
            "    return subprocess.run(['git', 'show', 'HEAD:task-packs/FORWARD_LEDGER.md']).stdout\n"
            "def beside(rf):\n"
            "    t = Path('task-packs/FORWARD_LEDGER.md').read_text()\n"
            "    raw = Path('task-packs/FORWARD_LEDGER.md').read_text()\n"
            "    return rf.ledger_view_at(Path('x'), ledger_text=t), raw\n", encoding="utf-8")
        (cc / "importer.py").write_text(
            "import generate_ledger_regions as g\n"
            "def via_import():\n"
            "    return g._LEDGER.read_text()\n", encoding="utf-8")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_planted.py").write_text(
            "REPO_ROOT = None\n"
            "def test_live():\n"
            "    (REPO_ROOT / 'task-packs' / 'FORWARD_LEDGER.md').read_text()\n"
            "def test_live_held():\n"
            "    ledger = REPO_ROOT / 'task-packs' / 'FORWARD_LEDGER.md'\n"
            "    ledger.read_text()\n"
            "class TestLive:\n"
            "    _LIVE = REPO_ROOT / 'task-packs' / 'LEDGER_PROBES.json'\n"
            "    def test_attr(self):\n"
            "        self._LIVE.read_text()\n"
            "def test_scratch(tmp_path):\n"
            "    (tmp_path / 'task-packs' / 'FORWARD_LEDGER.md').read_text()\n", encoding="utf-8")
        found = _unexplained_reads(tmp_path)
        assert sorted(f.split(" ", 1)[1].split(":")[0] for f in found) == [
            "_ledger_view", "beside", "held", "opened", "rows", "shown",
            "test_attr", "test_live", "test_live_held", "via_import"], found

    @pytest.mark.contract
    def test_the_census_sees_the_round_two_shapes(self, tmp_path):
        """The four shapes round 2 drove past the census that are cheap to
        hold: a read through a one-hop helper (called with the path, or by a
        caller that passes it on), a search in a child process, a glob over
        the task-pack folder, and a constant imported from another module.
        Dies to: any of those branches dropped. Not held here, by decision
        (the ledger row filed 2026-10-13): a helper calling a helper, and a
        credited read whose raw text is also used elsewhere."""
        cc = tmp_path / "tools" / "cc"
        cc.mkdir(parents=True)
        (cc / "planted.py").write_text(
            "import json, subprocess\n"
            "from pathlib import Path\n"
            "def _read_json(path):\n"
            "    return json.loads(path.read_text())\n"
            "def via_helper():\n"
            "    return _read_json(Path('task-packs/LEDGER_PROBES.json'))\n"
            "def _marked(path):\n"
            "    return path.read_text()  # ledger-read: a reason that covers each caller\n"
            "def via_marked():\n"
            "    return _marked(Path('task-packs/FORWARD_LEDGER.md'))\n"
            "def via_search():\n"
            "    return subprocess.run(['grep', '-c', 'DEF-1', 'task-packs/FORWARD_LEDGER.md']).stdout\n"
            "def via_glob():\n"
            "    return [p.read_text() for p in Path('task-packs').glob('*.md')]\n"
            "def under_it():\n"
            "    return [p.read_text() for p in Path('task-packs/Done').glob('*.md')]\n"
            "def via_checkout():\n"
            "    return [p.read_text() for p in checkout_glob(Path('task-packs'), '*.md')]\n"
            "def under_it_routed():\n"
            "    return [p.read_text() for p in checkout_rglob(Path('task-packs/Done'), '*.md')]\n", encoding="utf-8")
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "imports.py").write_text(
            "from board import LEDGER\n"
            "def via_constant(root):\n"
            "    return (root / LEDGER).read_text()\n", encoding="utf-8")
        found = _unexplained_reads(tmp_path)
        assert sorted(f.split(" ", 1)[1].split(":")[0] for f in found) == [
            "via_checkout", "via_constant", "via_glob", "via_helper", "via_search"], found


class TestTheRecordPredicates:
    """``is_ledger_record`` / ``is_dated_fragment``: the one answer a sweep that
    exempts a record by its file name takes, so a row in its own file is held
    the same way. Before them a struck row file would have redded the citation
    calibration (only ``FORWARD_LEDGER.md`` was exempt) the first time any seat
    struck one (failure-mode review, driven 2026-10-13)."""

    @pytest.mark.parametrize("rel, ledger, dated", [
        ("task-packs/FORWARD_LEDGER.md", True, False),
        ("task-packs/LEDGER_PROBES.json", True, False),
        ("task-packs/ledger.d/DEF-9.md", True, False),
        ("task-packs\\probes.d\\DEF-9.json", True, False),
        ("memory/session-log.d/2026-10-13-120000-air.md", False, True),
        ("changelog.d/2026-10-13-lane.md", False, True),
        ("task-packs/TP-1-x.md", False, False),
        ("docs/HOOKS.md", False, False),
    ])
    def test_each_shape(self, frag, rel, ledger, dated):
        """Dies to: either predicate keyed on the two file names alone."""
        assert frag.is_ledger_record(rel) is ledger
        assert frag.is_dated_fragment(rel) is dated

    def test_a_struck_row_files_lines_are_what_the_citation_sweep_exempts(self, lr, tmp_path):
        """The citation sweep's struck-row rule reads the lines a real strike
        writes into a row file as struck rows, and the file as the ledger's
        record, so the calibration that keeps the rule's reach honest holds."""
        from tests.test_doc_source_citations import _is_struck_row

        t = _opted_in_tree(tmp_path)
        assert _file(lr, t, "DEF-3") == 0 and _strike(lr, t, "DEF-3") == 0
        row = tmp_path / "task-packs" / "ledger.d" / "DEF-3.md"
        lines = row.read_text(encoding="utf-8").splitlines()[1:]
        assert lines and all(_is_struck_row(ln) for ln in lines)
        assert lr._FRAG.is_ledger_record(row.relative_to(tmp_path).as_posix())


class TestTheProseReadersNameBothForms:
    """A search COMMAND an instruction spells -- a code span or a fenced
    block that runs ``grep`` or ``rg`` over ``task-packs/FORWARD_LEDGER.md``
    or ``task-packs/LEDGER_PROBES.json`` -- names the row or probe files
    beside it (``task-packs/ledger.d/``, ``task-packs/probes.d/``) or reads
    the loader's view instead (``python tools/cc/_record_fragments.py ledger``
    or ``probes``). Told to search the file alone, a fan-out's dedup step, a
    pack-retirement census or a rename sweep finds nothing in a row filed as
    its own file, and passes (failure-mode review, 2026-10-13).

    What this decides, and only this: the command shape, which a session runs
    as written. An instruction in English -- "use the Grep tool on the
    ledger", "Read it", "the dedup source is the ledger" -- is a reader no
    pattern holds without flagging honest sentences as well (round-2 review:
    four of four honest sentences read as readers under a sentence-level
    rule, and seven reader shapes passed it). Those were swept by hand on
    2026-10-13, and ``DEF-4018`` keeps a count of the instruction-layer files
    that name either file and neither form."""

    #: The instruction layer: bodies, memory rules, the docs a session is told
    #: to follow, and the root documents a stranger reads. Packs are corrected
    #: when they run, and records are not edited (Core Rule 13), so neither is
    #: swept here.
    _DIRS = (".claude/", "memory/", "docs/")
    _FILES = ("README.md", "CONTRIBUTING.md", "CLAUDE.md", "task-packs/CLAUDE.md")
    _FENCE = re.compile(r"^\s*```")
    #: A code span: one backtick each side, at most one line break inside.
    _SPAN = re.compile(r"(?<!`)`(?!`)([^`\n]+(?:\n[^`\n]+)?)`(?!`)")
    #: In a workflow script every template literal is prose; a command in it
    #: is spelled between ESCAPED backticks.
    _JS_SPAN = re.compile(r"\\`([^`\n]+?)\\`")
    _RUNS_A_SEARCH = re.compile(r"\b(?:grep|rg)\b")
    #: Each file, and what a command over it names to read every row or probe.
    _NEEDS = ((re.compile(r"FORWARD_LEDGER\.md"), re.compile(r"ledger\.d|_record_fragments\.py\b.*\bledger\b", re.S)),
              (re.compile(r"LEDGER_PROBES\.json"), re.compile(r"probes\.d|_record_fragments\.py\b.*\bprobes\b", re.S)))

    @classmethod
    def _misses(cls, unit: str) -> bool:
        return bool(cls._RUNS_A_SEARCH.search(unit)) and any(
            names.search(unit) and not reads_all.search(unit) for names, reads_all in cls._NEEDS)

    @classmethod
    def _offenders(cls, root: Path, rels: list[str]) -> list[str]:
        """``path:line`` of each search command (a code span, or a fenced block
        taken whole) that runs over the ledger or roster file and names neither
        the files beside it nor the loader's verb for it."""
        from tests._record_paths import is_dated_fragment
        from tests.test_doc_source_citations import _RECORD_SURFACE_DOCS

        out = []
        for rel in sorted(rels):
            # A record keeps what was said on its day (Core Rule 13).
            if (not (rel in cls._FILES or rel.startswith(cls._DIRS)) or not rel.endswith((".md", ".js"))
                    or rel in _RECORD_SURFACE_DOCS or is_dated_fragment(rel)):
                continue
            if rel.endswith(".js"):
                text = (root / rel).read_text(encoding="utf-8", errors="replace")
                out.extend(f"{rel}:{text.count(chr(10), 0, m.start()) + 1}"
                           for m in cls._JS_SPAN.finditer(text) if cls._misses(m.group(1)))
                continue
            lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
            masked: list[str] = []
            block: list[str] | None = None
            start = 0
            for i, line in enumerate(lines):
                if cls._FENCE.match(line):
                    if block is None:
                        block, start = [], i + 2
                    else:
                        if cls._misses("\n".join(block)):
                            out.append(f"{rel}:{start}")
                        block = None
                    masked.append("")
                elif block is not None:
                    block.append(line)
                    masked.append("")
                else:
                    masked.append(line)
            text = "\n".join(masked)
            out.extend(f"{rel}:{text.count(chr(10), 0, m.start()) + 1}"
                       for m in cls._SPAN.finditer(text) if cls._misses(m.group(1)))
        return sorted(set(out), key=lambda s: (s.rsplit(":", 1)[0], int(s.rsplit(":", 1)[1])))

    @pytest.mark.contract
    def test_no_command_searches_the_ledger_file_alone(self):
        from tests._git_oracle import require_tracked_paths  # never a silently empty set

        rels = require_tracked_paths(REPO_ROOT, *self._DIRS, *self._FILES, minimum=100,
                                     what="instruction-layer files")
        found = self._offenders(REPO_ROOT, rels)
        assert not found, ("search commands over task-packs/FORWARD_LEDGER.md or LEDGER_PROBES.json that "
                           "read neither the row/probe files beside them nor `python "
                           "tools/cc/_record_fragments.py ledger|probes`: " + ", ".join(found))

    def test_the_scan_sees_each_command_shape_and_passes_honest_text(self, tmp_path):
        """Dies to: rg or the roster left out, a span wrapped over a line
        break read as two, a fence read line by line, a root or a root file
        dropped, or a record swept. The honest lines are round 2's four that
        the sentence-level rule flagged."""
        ledger, roster = "task-packs/FORWARD_LEDGER.md", "task-packs/LEDGER_PROBES.json"
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        (tmp_path / ".claude" / "commands" / "x.md").write_text("\n".join([
            f"`grep -n DEF-1 {ledger}`",                                       # 1 red
            f"`rg -n DEF-1 {ledger}`",                                         # 2 red
            f"`grep -n DEF-1 {roster}`",                                       # 3 red
            "verify after any batch: `command grep -c '<id>'",                  # 4 red, wrapped
            f"{ledger}` per id",
            "```bash",
            f"grep -c DEF-1 {ledger}",                                          # 7 red, a fence
            "```",
            "```bash",
            f"grep -c DEF-1 {ledger}",                                          # whole fence: fine
            "grep -c DEF-1 task-packs/ledger.d/*.md",
            "```",
            f"`grep -rn DEF-1 {ledger} task-packs/ledger.d`",
            f"Never grep {ledger} for a count; the generator's --print is the count.",
            f"`git grep -n DEF-1` searches every tracked file, {ledger} and its row files alike.",
            f"`python3 tools/cc/_record_fragments.py --root . ledger | grep DEF-1`, never {ledger} alone.",
            "`grep -rn DEF-1 task-packs/` reads FORWARD_LEDGER.md and every row file under it.",
            "`python tools/cc/_record_fragments.py probes | grep DEF-1`",
        ]) + "\n", encoding="utf-8")
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "y.md").write_text(f"`grep DEF-1 {ledger}`\n", encoding="utf-8")
        (tmp_path / "README.md").write_text(f"`grep DEF-1 {ledger}`\n", encoding="utf-8")
        (tmp_path / "memory").mkdir()
        (tmp_path / "memory" / "CONVERGENCE_LEDGER.md").write_text(f"`grep {ledger}`\n", encoding="utf-8")
        (tmp_path / ".claude" / "workflows").mkdir()
        (tmp_path / ".claude" / "workflows" / "w.js").write_text(
            f"const D =\n  `1. DEDUP: grep the forward ledger: {ledger} and,\\n` +\n"     # prose: fine
            f"  `   task-packs/ledger.d/ (\\`grep -n DEF-1 {ledger}\\`)\\n`;\n",          # 3 red
            encoding="utf-8")
        rels = [".claude/commands/x.md", ".claude/workflows/w.js", "docs/y.md", "README.md",
                "memory/CONVERGENCE_LEDGER.md"]
        assert self._offenders(tmp_path, rels) == [
            ".claude/commands/x.md:1", ".claude/commands/x.md:2", ".claude/commands/x.md:3",
            ".claude/commands/x.md:4", ".claude/commands/x.md:7", ".claude/workflows/w.js:3",
            "README.md:1", "docs/y.md:1"]


class TestTheEnginesPathSites:
    """Where the engine names the two files as files the verbs rewrite, it
    names the two directories beside them."""

    def test_the_formatter_ignore_lines_name_the_row_file_directories(self, tmp_path):
        """A formatter that reflows a row file changes its ``row_sha`` and
        flips its probe to a stale claim, as it would the ledger. Dies to: the
        directories left off the lines init and upgrade print."""
        from espalier import cli

        packs = tmp_path / "task-packs"
        (packs / "ledger.d").mkdir(parents=True)
        (packs / "ledger.d" / "DEF-9.md").write_text(_row_file("DEF-9"), encoding="utf-8")
        (packs / "probes.d").mkdir()
        lines = cli._ignore_snippet_lines(tmp_path)
        assert "task-packs/ledger.d/" in lines and "task-packs/probes.d/" in lines


class TestTheProbeRunnerReadsTheView:
    """``check_ledger_probes.py`` reads the ledger's and the roster's views:
    a row file and a probe file count like a row and an entry in the files."""

    @staticmethod
    def _json(chk, root: Path, capsys) -> tuple[int, dict]:
        rc = chk.main(["--root", str(root), "--json"])
        out = capsys.readouterr().out
        return rc, json.loads(out[out.index("{"):])

    def test_a_row_files_probe_file_is_its_entry(self, chk, tmp_path, capsys):
        """Dies to: the unprobed-row note reading the roster file alone (the
        row file's probe file is not seen) or the ledger file alone (the row
        file is not seen)."""
        root = _fragment_tree(tmp_path, rows={"DEF-9.md": _row_file("DEF-9"), "DEF-8.md": _row_file("DEF-8")},
                              probes={"DEF-9.json": {"id": "DEF-9", "subject": "s", "why_not": "x"}})
        _rc, report = self._json(chk, root, capsys)
        assert report["unprobed_live_rows"] == ["DEF-8"]
        assert "DEF-9" in {r["id"] for r in report["results"]}

    def test_a_struck_row_files_probe_is_retired(self, chk, tmp_path):
        """Dies to: the retired filter reading the ledger file alone."""
        root = _fragment_tree(tmp_path, rows={"DEF-9.md": _row_file("DEF-9", struck=True)})
        saved = chk._LEDGER
        chk._LEDGER = root / "task-packs" / "FORWARD_LEDGER.md"
        try:
            assert chk.retired_ids([{"id": "DEF-9"}, {"id": "DEF-1"}]) == {"DEF-9"}
        finally:
            chk._LEDGER = saved

    def test_probe_files_without_a_roster_file_are_still_run(self, chk, tmp_path, capsys):
        """Dies to: a missing roster file read as "no probes" while probe
        files sit beside it."""
        from tests.test_generate_ledger_regions import _ledger

        root = _fragment_tree(tmp_path, ledger=_ledger(c1_rows=(), appendix=()),
                              rows={"DEF-9.md": _row_file("DEF-9")},
                              probes={"DEF-9.json": {"id": "DEF-9", "subject": "s", "why_not": "x"}})
        (root / "task-packs" / "LEDGER_PROBES.json").unlink()
        _rc, report = self._json(chk, root, capsys)
        assert [r["id"] for r in report["results"]] == ["DEF-9"]

    def test_a_probe_file_that_does_not_parse_is_refused(self, chk, tmp_path, capsys):
        """Dies to: an unreadable probe file read as no probe."""
        root = _fragment_tree(tmp_path, rows={"DEF-9.md": _row_file("DEF-9")})
        (root / "task-packs" / "probes.d" / "DEF-9.json").write_text("{", encoding="utf-8")
        assert chk.main(["--root", str(root)]) == 1
        assert "DEF-9.json: not JSON" in capsys.readouterr().out


class TestTheRecordMergeReadsTheView:
    """``record_merge.regenerate_ledger`` checks the merged ledger with the
    row files the merge left on disk placed in it."""

    def test_a_struck_row_file_keeping_its_probe_file_does_not_converge(self, tmp_path):
        """Dies to: the merge checking the ledger file alone (the struck row
        file is not seen, so its live probe file reads as nobody's)."""
        rm = _load("record_merge")
        root = _fragment_tree(tmp_path, rows={"DEF-9.md": _row_file("DEF-9", struck=True)},
                              probes={"DEF-9.json": {"id": "DEF-9", "subject": "s"}})
        gen = rm._load_sibling("generate_ledger_regions")
        text = (root / "task-packs" / "FORWARD_LEDGER.md").read_text(encoding="utf-8")
        with pytest.raises(rm.Unresolvable, match="does not converge"):
            rm.regenerate_ledger(text, gen, root / "task-packs" / "LEDGER_PROBES.json")

    def test_a_merged_ledger_with_placed_row_files_converges_and_is_returned_as_the_file(self, tmp_path):
        """Dies to: the merge writing the view back (the row file's line in
        the text it returns)."""
        rm = _load("record_merge")
        root = _fragment_tree(tmp_path, rows={"DEF-9.md": _row_file("DEF-9")},
                              probes={"DEF-9.json": {"id": "DEF-9", "subject": "s"}})
        gen = rm._load_sibling("generate_ledger_regions")
        text = (root / "task-packs" / "FORWARD_LEDGER.md").read_text(encoding="utf-8")
        assert rm.regenerate_ledger(text, gen, root / "task-packs" / "LEDGER_PROBES.json") == text


class TestTheBoardAndTheLandingCheckReadTheView:
    """The board's live count and the landing check's two ledger reads take
    the views, so a row or probe that lives in its own file counts."""

    def test_the_boards_live_count_counts_a_row_file(self, tmp_path):
        """Dies to: the board counting the ledger file alone."""
        board = _load("board")
        root = _fragment_tree(tmp_path, rows={"DEF-9.md": _row_file("DEF-9")})
        assert board.read_ledger_live(root) == 3

    @staticmethod
    def _landing(monkeypatch, root: Path):
        spec = importlib.util.spec_from_file_location("_lf_landing", REPO_ROOT / "scripts" / "check_handoff_landing.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        monkeypatch.setattr(mod, "REPO_ROOT", root)
        return mod

    def test_a_prefix_minted_in_a_row_file_is_a_ledger_prefix(self, tmp_path, monkeypatch):
        """Dies to: the prefixes derived from the ledger file alone."""
        root = _fragment_tree(tmp_path, rows={"QQ-1.md": _row_file("QQ-1")})
        assert "QQ" in self._landing(monkeypatch, root).ledger_prefixes()

    def test_a_probe_files_row_sha_is_known(self, tmp_path, monkeypatch):
        """Dies to: the row shas read from the roster file alone."""
        root = _fragment_tree(tmp_path, rows={"DEF-9.md": _row_file("DEF-9")},
                              probes={"DEF-9.json": {"id": "DEF-9", "row_sha": "abcdef123456"}})
        assert "abcdef123456" in self._landing(monkeypatch, root)._known_row_shas()


class TestTheTrendReadsTheViewAtEachCommit:
    """``scripts/ledger_trend.py`` walks the commits that touched the ledger or
    its row-file directory, and reads the view at each."""

    @staticmethod
    def _trend():
        spec = importlib.util.spec_from_file_location("_lf_trend", REPO_ROOT / "scripts" / "ledger_trend.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_a_commit_that_only_files_a_row_file_is_a_snapshot_and_reads_it(self, tmp_path):
        """Dies to: the walk logging the ledger file alone (the commit is not a
        snapshot), or the read showing the file alone (the row is not in it)."""
        trend = self._trend()
        repo = _Repo(tmp_path, opted_in=True)
        row = tmp_path / "task-packs" / "ledger.d" / "DEF-9.md"
        row.parent.mkdir(parents=True)
        row.write_text(_row_file("DEF-9"), encoding="utf-8")
        repo.commit("a row file only")
        snaps = trend.snapshots(tmp_path, "HEAD", "task-packs/FORWARD_LEDGER.md")
        assert len(snaps) == 2
        text = trend.ledger_at(tmp_path, snaps[-1][0], "task-packs/FORWARD_LEDGER.md")
        assert "| `DEF-9` | site/DEF-9 |" in text
        assert "DEF-9" not in trend.ledger_at(tmp_path, snaps[0][0], "task-packs/FORWARD_LEDGER.md")


class TestTheSymbolCensusReadsRowFilesLikeTheLedger:
    """``scripts/symbol_census.py``: a live row file is live text (a renamed
    symbol in it needs sweeping, as in the ledger); a struck row's line is a
    record that keeps the old name on purpose."""

    def test_live_and_struck_row_files_are_classed_like_ledger_rows(self, tmp_path):
        """Dies to: row files read wholesale as records, or struck lines as live."""
        spec = importlib.util.spec_from_file_location("_lf_symbol_census", REPO_ROOT / "scripts" / "symbol_census.py")
        census_mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = census_mod
        spec.loader.exec_module(census_mod)
        repo = _Repo(tmp_path, opted_in=True)
        rows = tmp_path / "task-packs" / "ledger.d"
        rows.mkdir(parents=True)
        (rows / "DEF-9.md").write_text(
            "<!-- class: §C1 -->\n| `DEF-9` | tools/cc/x.py::old_symbol_name | what | nit |\n"
            "| `DEF-9` | §C1 | site |\n", encoding="utf-8")
        (rows / "DEF-8.md").write_text(
            "<!-- class: §C1 -->\n| ~~`DEF-8`~~ | site | CLOSED. PRIOR TEXT: old_symbol_name | nit |\n"
            "| ~~`DEF-8`~~ | §C1 | site |\n", encoding="utf-8")
        repo.commit("row files")
        hits = census_mod.census(tmp_path, ["old_symbol_name"])["hits"]
        kinds = {h["path"].rsplit("/", 1)[-1]: h["kind"] for h in hits}
        assert kinds == {"DEF-9.md": "live", "DEF-8.md": "record"}, hits


class TestConvergenceReadsThePendingView:
    """``ledger_row._converge`` checks what the write WILL leave: the row
    files on disk with the pending ones applied."""

    def test_a_pending_row_file_the_view_cannot_place_is_drift(self, lr, tmp_path):
        """Dies to: a convergence that checks the file without the pending
        row files (the verbs' own checks run first, so only this test sees it)."""
        t = _opted_in_tree(tmp_path)
        pending = lr._Pending(t["ledger"], t["probes"])
        pending.rows[tmp_path / "task-packs" / "ledger.d" / "DEF-9.md"] = _row_file("DEF-9", "§C7")
        gen = lr._load("generate_ledger_regions")
        _text, drift = lr._converge(gen, t["ledger"].read_text(encoding="utf-8"), t["probes"], pending)
        assert any(d["region"] == "row-files" and "§C7" in d["detail"] for d in drift), drift

    def test_a_pending_struck_row_keeping_its_probe_file_is_drift(self, lr, tmp_path):
        """The struck row is pending, its probe file is on disk. Dies to: the
        pending rows left out of the view (the row reads live)."""
        t = _opted_in_tree(tmp_path)
        packs = tmp_path / "task-packs"
        (packs / "probes.d").mkdir()
        (packs / "probes.d" / "DEF-9.json").write_text(json.dumps({"id": "DEF-9"}) + "\n", encoding="utf-8")
        pending = lr._Pending(t["ledger"], t["probes"])
        pending.rows[packs / "ledger.d" / "DEF-9.md"] = _row_file("DEF-9", struck=True)
        gen = lr._load("generate_ledger_regions")
        _text, drift = lr._converge(gen, t["ledger"].read_text(encoding="utf-8"), t["probes"], pending)
        assert any("DEF-9: struck in its class section but still carries a probe" in d["detail"]
                   for d in drift), drift


# ── the fold (TP-479a Wave C) ───────────────────────────────────────────────

_ROSTER_REL = "task-packs/LEDGER_PROBES.json"
_LEDGER_REL = "task-packs/FORWARD_LEDGER.md"


def _view_parts(frag, ledger_text: str, row_files, roster_text, probe_files):
    """The view, taken apart for a row-for-row comparison: every line that is
    not a member row or an Appendix B index row, in order; each class table's
    rows and Appendix B's as a multiset; each probe by its id; and what the
    loader could not read. Order within a table is not compared: the view
    places row files in id order, and the legacy tables were not."""
    from collections import Counter

    view = frag.ledger_view_from_texts(ledger_text, row_files)
    roster = frag.probe_roster_from_texts(roster_text, probe_files)
    lines = view.text.split("\n")
    owner: dict[int, str] = {}
    for section, (start, end) in frag._section_bounds(lines).items():
        for j in range(start, end):
            if frag.row_ids(lines[j]):
                owner[j] = section
    app = next((i for i, ln in enumerate(lines) if ln.startswith("## Appendix B")), None)
    if app is not None:
        end = next((j for j in range(app + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
        owner.update({j: "Appendix B" for j in range(app + 1, end) if frag._APPENDIX_B_ROW_RE.match(lines[j])})
    tables: dict[str, Counter] = {}
    for j, section in owner.items():
        tables.setdefault(section, Counter())[lines[j]] += 1
    other = [ln for j, ln in enumerate(lines) if j not in owner]
    probes = {entry["id"]: entry for entry in roster.data["probes"]}
    return other, tables, probes, view.problems + roster.problems


@pytest.fixture(scope="module")
def trend():
    """``scripts/ledger_trend.py``, whose commit reader (``_row_files_at``) the
    fold test reuses rather than copies."""
    spec = importlib.util.spec_from_file_location("_lf_ledger_trend", REPO_ROOT / "scripts" / "ledger_trend.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _git_here(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=45, check=False)


#: The fold's commit: the data move alone, 2026-10-14. Named, never found as
#: "the latest commit that deleted the roster": a later commit that deletes it
#: again (a pre-fold lane's catch-up repaired by a new commit) would stand in
#: for it and compare two folded trees.
_FOLD_COMMIT = "5b04f16a9d7a4907607530db524643333fd75325"


def _folded() -> bool | None:
    """Whether this tree's history holds the fold: True or False, or None when
    git cannot say (no git, a shallow clone, a release export's seeded history,
    an adopter's repository). Decided by history, never by the
    ``ledger_fragments`` setting, whose flip the live pin exists to catch."""
    if _git_here("cat-file", "-e", f"{_FOLD_COMMIT}^{{commit}}").returncode != 0:
        return None
    return _git_here("merge-base", "--is-ancestor", _FOLD_COMMIT, "HEAD").returncode == 0


def _parts_at(frag, trend, commit: str):
    """The view's parts at ``commit``: the two files (the roster absent after
    the fold) and the row and probe files beside them, read from git."""
    ledger = _git_here("show", f"{commit}:{_LEDGER_REL}")
    assert ledger.returncode == 0, ledger.stderr
    roster = _git_here("show", f"{commit}:{_ROSTER_REL}")
    rows = trend._row_files_at(REPO_ROOT, commit, "task-packs/ledger.d")
    probes = trend._row_files_at(REPO_ROOT, commit, "task-packs/probes.d")
    return _view_parts(frag, ledger.stdout, rows, roster.stdout if roster.returncode == 0 else None, probes)


class TestTheFold:
    """The fold moved every legacy row and probe into a file of its own in one
    commit (TP-479a Wave C): the class tables and Appendix B keep their header
    and rule, the roster's prose lives in ``task-packs/probes.d/README.md``,
    and the roster file is gone. Readers see the same rows before and after,
    row for row; byte for byte was never possible, since 21 class tables,
    Appendix B and the roster were not in id order and the view orders row
    files by id."""

    def test_the_views_at_the_fold_commit_are_equal_row_for_row(self, frag, trend):
        folded = _folded()
        if folded is None:
            pytest.skip("git cannot reach the fold's commit here (no git, a shallow clone, a release "
                        "export's seeded history, or another repository)")
        if not folded:
            pytest.skip("this tree's history does not hold the fold (a lane branched before it)")
        before = _parts_at(frag, trend, f"{_FOLD_COMMIT}^")
        after = _parts_at(frag, trend, _FOLD_COMMIT)
        assert not before[3] and not after[3], (before[3][:5], after[3][:5])
        assert before[0] == after[0], "a line that is not a row moved or changed at the fold"
        assert before[1] == after[1], "a class table's rows or Appendix B's differ before and after the fold"
        assert before[2] == after[2], "a probe differs before and after the fold"
        assert sum(len(c) for c in after[1].values()) >= 900, "the fold's view read almost no rows: the walk broke"

    def test_the_comparison_reads_a_lost_row_a_lost_index_line_and_a_changed_probe(self, frag):
        """The comparison's own control, on planted texts: a row file dropped,
        an index line dropped, or a probe's value changed reads as unequal."""
        ledger = ("# L\n\n### §C1 — one\n\n| id | site |\n|---|---|\n\n## Appendix B\n\n| id | class | site |\n"
                  "|---|---|---|\n")
        rows = [("DEF-1.md", _row_file("DEF-1")), ("DEF-2.md", _row_file("DEF-2"))]
        probes = [("DEF-1.json", json.dumps({"id": "DEF-1", "open_value": "True"}) + "\n")]
        whole = _view_parts(frag, ledger, rows, None, probes)
        assert not whole[3], whole[3]
        assert _view_parts(frag, ledger, rows[:1], None, probes)[1] != whole[1]
        lost_index = [(n, t.rsplit("\n| `", 1)[0] + "\n") if n == "DEF-2.md" else (n, t) for n, t in rows]
        assert _view_parts(frag, ledger, lost_index, None, probes)[1] != whole[1]
        changed = [("DEF-1.json", json.dumps({"id": "DEF-1", "open_value": "False"}) + "\n")]
        assert _view_parts(frag, ledger, rows, None, changed)[2] != whole[2]

    @pytest.mark.contract
    def test_this_tree_keeps_rows_and_probes_only_as_files(self, frag):
        """After the fold the big file holds no member row and no index row and
        the roster file is gone, so a lane branched before the fold cannot bring
        a legacy row or the roster back unseen (the loader would read the row
        twice, or the roster beside its probe files). Each class table and
        Appendix B keep the header and rule the view places rows under. Whether
        the tree has folded is read from history, so turning
        ``ledger_fragments`` off, which sends the verbs back to the big files,
        reds here instead of skipping (failure-mode review, driven 2026-10-14)."""
        folded = _folded()
        if folded is None:
            pytest.skip("git cannot reach the fold's commit here (no git, a shallow clone, a release "
                        "export's seeded history, or another repository)")
        if not folded:
            pytest.skip("this tree's history does not hold the fold (a lane branched before it)")
        on, how = frag.ledger_fragments_setting(REPO_ROOT)
        assert on, (f"ledger_fragments is off ({how}), so the ledger verbs write rows and the roster back "
                    "into the big files the fold emptied: set `ledger_fragments = true` in espalier.toml")
        assert not (REPO_ROOT / _ROSTER_REL).exists(), (
            f"{_ROSTER_REL} is back: a lane branched before the fold kept it at its catch-up. Its probes "
            "live in task-packs/probes.d/ now: `git rm` the file and amend the catch-up merge, then re-run "
            "that lane's ledger verb (file, strike, repin) on the merged tree")
        text = (REPO_ROOT / _LEDGER_REL).read_bytes().decode("utf-8").replace("\r\n", "\n")  # ledger-read: the file's own lines, which must hold no row after the fold
        lines = text.split("\n")
        bounds = frag._section_bounds(lines)
        legacy = [lines[j][:60] for start, end in bounds.values() for j in range(start, end) if frag.row_ids(lines[j])]
        app = next(i for i, ln in enumerate(lines) if ln.startswith("## Appendix B"))
        end = next((j for j in range(app + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
        legacy += [lines[j][:60] for j in range(app + 1, end) if frag._APPENDIX_B_ROW_RE.match(lines[j])]
        assert not legacy, (f"{len(legacy)} row(s) in {_LEDGER_REL} itself: every row lives in "
                            "task-packs/ledger.d/ since the fold; take main's side for the file in the "
                            f"catch-up merge and re-run that lane's ledger verb on the merged tree: {legacy[:3]}")
        unplaceable = [s for s, (start, end) in bounds.items()
                       if frag._table_end(lines, start, end, frag._MEMBER_ROW_RE) is None]
        assert not unplaceable, f"class sections with no table for the view to place rows in: {unplaceable}"
        assert frag._table_end(lines, app + 1, end, frag._APPENDIX_B_ROW_RE) is not None, "Appendix B lost its table"
