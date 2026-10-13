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
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_ledger_row import _args, _build_tree

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
        assert len(got.problems) == 2 and got.skipped == ["notes.json"] and got.data["probes"] == []

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
_RECORD_NAMES = ("FORWARD_LEDGER.md", "LEDGER_PROBES.json")
_VERB_MODULES = ("ledger_row", "generate_ledger_regions", "check_ledger_probes", "record_merge")
#: A read's target that names the ledger or its roster (a path, a constant, a
#: variable), never a module's own source file.
_RECORD_TARGET_RE = re.compile(r"(?i)ledger|probes")
_MODULE_SOURCE_RE = re.compile(r"\.py\b")
#: In a test, only a read of the LIVE tree is a reader; a scratch fixture is
#: read for what a verb wrote to it.
_LIVE_TREE_RE = re.compile(r"REPO_ROOT|\b_ROOT\b|parents\[|gen\._LEDGER|gen\._PROBES|\b_LEDGER\b|\b_PROBE_FILE\b")
#: The names that reach the loader's view: its functions, and the helpers that
#: return it. Read from a function's CODE (names and attributes), never from
#: its docstring or comments, which can name the loader without calling it.
_LOADER_NAMES = frozenset({
    "record_fragments", "ledger_view_at", "probe_roster_at", "ledger_text_from_texts",
    "ledger_view_from_texts", "probe_roster_from_texts", "_view", "_ledger_view",
    "_live_roster_probes", "_row_home",
})
_LEDGER_READ = "# ledger-read:"


def _reaches_loader(fn: ast.AST) -> bool:
    """Whether a function's code names a loader function or a view helper
    (``pending.view`` included), its own name and docstring left out."""
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and node.id in _LOADER_NAMES:
                return True
            if isinstance(node, ast.Attribute):
                if node.attr in _LOADER_NAMES:
                    return True
                if node.attr == "view" and isinstance(node.value, ast.Name) and node.value.id == "pending":
                    return True
    return False


def _string_constants(tree: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _record_reads(rel: str, text: str, tree: ast.AST) -> list[tuple[int, str, str]]:
    """``(line, enclosing function, target)`` for every read of a ledger record
    in one module that names a record or loads a verb module."""
    consts = _string_constants(tree)
    if not (any(r in c for c in consts for r in _RECORD_NAMES) or any(v in c for c in consts for v in _VERB_MODULES)):
        return []
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f, target = node.func, None
        if isinstance(f, ast.Attribute) and f.attr in ("read_text", "read_bytes"):
            target = f.value
        elif isinstance(f, ast.Name) and f.id == "open" and node.args:
            target = node.args[0]
        elif isinstance(f, ast.Attribute) and f.attr in ("load", "loads") and node.args:
            target = node.args[0]
        if target is None:
            continue
        src = ast.get_source_segment(text, target) or ""
        if not _RECORD_TARGET_RE.search(src) or _MODULE_SOURCE_RE.search(src):
            continue
        if rel.startswith("tests/") and not _LIVE_TREE_RE.search(src):
            continue
        enclosing = [fn for fn in funcs if fn.lineno <= node.lineno <= (fn.end_lineno or fn.lineno)]
        out.append((node.lineno, enclosing[-1].name if enclosing else "<module>", src))
    return out


def _unexplained_reads(root: Path) -> list[str]:
    """Every read of a ledger record under the census roots whose function
    does not reach the loader and whose line names no reason. The loader is
    the one module that reads the files themselves."""
    found = []
    for base in _CENSUS_ROOTS:
        for p in sorted((root / base).rglob("*.py")):
            rel = p.relative_to(root).as_posix()
            if "/_vendor/" in rel or "/assets/" in rel or rel == "tools/cc/_record_fragments.py":
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            if not any(name in text for name in (*_RECORD_NAMES, *_VERB_MODULES)):
                continue   # a cheap pre-filter: the AST arm below asks the same of string constants
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            reads = _record_reads(rel, text, tree)
            if not reads:
                continue
            lines = text.splitlines()
            # Judged by the function's code: a helper named for the view
            # (`_ledger_view`) or a docstring naming the loader vouches for nothing.
            reaches = {fn.name: _reaches_loader(fn)
                       for fn in ast.walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for line, fn, src in reads:
                if _LEDGER_READ in lines[line - 1] or reaches.get(fn, False):
                    continue
                found.append(f"{rel}:{line} {fn}: {src[:70]}")
    return found


class TestTheReaderCensus:
    """Every reader of the ledger or its roster reads the loader's view, or
    names why it reads the file itself. A reader that reads the file alone
    does not red when a row moves into a file: it reads less and passes, which
    is the blocker the parent pack's own sweep found (a ship check that read
    one file and refused every handoff). Derived by AST over tools/cc, scripts,
    espalier and the tests that read the live tree."""

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
            for p in sorted((REPO_ROOT / base).rglob("*.py")):
                rel = p.relative_to(REPO_ROOT).as_posix()
                if "/_vendor/" in rel or rel == "tests/test_ledger_fragments.py":
                    continue
                for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if _LEDGER_READ in line and not line.split(_LEDGER_READ, 1)[1].strip():
                        bare.append(f"{rel}:{n}")
        assert not bare, f"`{_LEDGER_READ}` with no reason: {bare}"

    @pytest.mark.contract
    def test_the_census_sees_a_planted_reader_and_reads_the_exits(self, tmp_path):
        """Dies to: a census blind to a new module, to the live-tree arm in
        tests, or that takes a marker without reading it."""
        cc = tmp_path / "tools" / "cc"
        cc.mkdir(parents=True)
        (cc / "planted.py").write_text(
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
            "    return Path('task-packs/FORWARD_LEDGER.md').read_text()\n", encoding="utf-8")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_planted.py").write_text(
            "REPO_ROOT = None\n"
            "def test_live():\n"
            "    (REPO_ROOT / 'task-packs' / 'FORWARD_LEDGER.md').read_text()\n"
            "def test_scratch(tmp_path):\n"
            "    (tmp_path / 'task-packs' / 'FORWARD_LEDGER.md').read_text()\n", encoding="utf-8")
        found = _unexplained_reads(tmp_path)
        assert sorted(f.split(" ", 1)[1].split(":")[0] for f in found) == ["_ledger_view", "rows", "test_live"], found


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
