"""A row filed as a sibling of another records its parents, and two filing
advisories and a read-only verb read the chain.

``tools/cc/ledger_row.py file --sibling-of <id>`` writes the new row's parents
into a lineage file of its own beside the ledger, ``task-packs/lineage.d/<id>.json``
(in either ledger mode), which no strike or repin touches, so a chain survives
the strike of a row in its middle. The chain advisory reads it at filing
(recording-only by default: one line); the standalone-cluster advisory counts
the live standalone rows on the new row's site family; ``lineage <id>`` prints
a row's chain, its family's count and the five questions, and writes nothing.
It pins that a strike never cuts a chain, because a parent kept anywhere a
strike rewrites would vanish with its row; and that no advisory refuses,
because advice that blocks a filing is a gate nobody asked for. Every test
here was seen red against the mutation its docstring names.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests.test_generate_ledger_regions import _ledger
from tests.test_ledger_fragments import _close_probe
from tests.test_ledger_row import _args, _build_tree

# slow-exempt: each case drives the real verbs on a scratch ledger (measured
# under 0.1 s a filing); the files the verb leaves are the thing under test.

REPO_ROOT = Path(__file__).resolve().parents[1]
CC = REPO_ROOT / "tools" / "cc"


def _load_ledger_row():
    spec = importlib.util.spec_from_file_location("_lineage_ledger_row", CC / "ledger_row.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def lr():
    return _load_ledger_row()


@pytest.fixture(autouse=True)
def _away_from_the_live_tree(tmp_path, monkeypatch):
    """A verb run without ``--root`` walks up from the working directory to
    this checkout, whose ``espalier.toml`` would then govern the fixture."""
    monkeypatch.chdir(tmp_path)


#: The standalone rows the cluster fixture seeds: four on one site family,
#: and one each on two others.
_GUARD = "tools/cc/hooks/write_guard.py"
_C0_ROWS = (
    f"| `DEF-10` | {_GUARD}::a | what | nit | HYGIENE | MAINTAINER |",
    f"| `DEF-11` | {_GUARD}::b (the `docs/A.md` note) | what | nit | HYGIENE | MAINTAINER |",
    f"| `DEF-12` | {_GUARD}::c | what | nit | HYGIENE | MAINTAINER |",
    f"| `DEF-13` | {_GUARD}::d | what | nit | HYGIENE | MAINTAINER |",
    "| `DEF-14` | espalier/cli.py::e | what | nit | HYGIENE | MAINTAINER |",
    "| `DEF-15` | scripts/x.py::f | what | nit | HYGIENE | MAINTAINER |",
)


def _tree(tmp_path: Path, *, opted_in: bool, c0_rows: tuple[str, ...] | None = None) -> dict:
    """The fixture ledger; with ``c0_rows``, its MIXED class renamed to the
    standalone class and seeded with those rows, each with a declared probe."""
    t = _build_tree(tmp_path)
    if c0_rows is not None:
        text = _ledger(mixed=True, c2_rows=c0_rows).replace("§C2", "§C0").replace("(#c2)", "(#c0)")
        t["ledger"].write_text(text, encoding="utf-8")
        data = json.loads(t["probes"].read_text(encoding="utf-8"))
        data["probes"] += [{"id": row.split("`")[1], "subject": "site", "cmd": None, "open_value": None,
                            "why_not": "fixture", "row_sha": "z"} for row in c0_rows]
        t["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    if opted_in:
        (tmp_path / "espalier.toml").write_text("ledger_fragments = true\n", encoding="utf-8")
    (tmp_path / "site").write_text("", encoding="utf-8")
    return t


def _file(lr, t, rid: str, *parents: str, section: str = "C1", after: str = "DEF-2",
          anchor: str | None = None, extra: tuple[str, ...] = (), pre: tuple[str, ...] = ()) -> int:
    root = t["ledger"].parents[1]
    tags = ("--population", "LOGIC_BUG", "--audience", "ADOPTER") if section == "C0" else ()
    return lr.main(_args(t, "--root", str(root), *pre, "file", rid, "--section", section, "--after", after,
                         "--anchor", anchor or f"a/{rid}.py", "--text-file", str(t["body"]),
                         "--severity", "nit", "--subject", "site", "--why-not", "no local oracle",
                         *tags, *[a for p in parents for a in ("--sibling-of", p)], *extra))


def _strike(lr, t, rid: str) -> int:
    root = t["ledger"].parents[1]
    _close_probe(t, rid)
    return lr.main(_args(t, "--root", str(root), "strike", rid, "--text-file", str(t["closing"]), "--no-base"))


def _lineage(lr, t, rid: str, capsys) -> tuple[int, str]:
    capsys.readouterr()
    rc = lr.main(_args(t, "--root", str(t["ledger"].parents[1]), "lineage", rid))
    return rc, capsys.readouterr().out


def _lineage_file(t, rid: str) -> Path:
    return t["ledger"].parent / "lineage.d" / f"{rid}.json"


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


_BOTH_MODES = pytest.mark.parametrize("opted_in", [False, True], ids=["ledger-file", "row-files"])


class TestASiblingRecordsItsParents:
    """``file --sibling-of`` writes one lineage file for the new row, naming
    its parents, in either ledger mode, and nothing else; a parent the ledger
    does not have is refused before anything is written."""

    @_BOTH_MODES
    def test_a_filing_writes_one_lineage_file_naming_its_parents_once_each(self, lr, tmp_path, opted_in):
        """Dies to: the flag parsed and dropped, or a parent repeated."""
        t = _tree(tmp_path, opted_in=opted_in)
        assert _file(lr, t, "DEF-5", "DEF-1", "DEF-2", "DEF-1") == 0
        assert json.loads(_lineage_file(t, "DEF-5").read_text(encoding="utf-8")) == {
            "id": "DEF-5", "sibling_of": ["DEF-1", "DEF-2"]}
        assert _file(lr, t, "DEF-6") == 0
        assert not _lineage_file(t, "DEF-6").exists(), "a filing with no --sibling-of wrote a lineage file"
        assert sorted(p.name for p in _lineage_file(t, "DEF-5").parent.iterdir()) == ["DEF-5.json"]

    @_BOTH_MODES
    def test_a_chain_survives_the_strike_of_its_middle_row(self, lr, tmp_path, opted_in, capsys):
        """Dies to: the strike unlinking the struck row's lineage file (a
        parent kept where a strike rewrites), which cuts the chain at DEF-5."""
        t = _tree(tmp_path, opted_in=opted_in)
        assert _file(lr, t, "DEF-5", "DEF-1") == 0
        assert _file(lr, t, "DEF-6", "DEF-5") == 0
        assert _strike(lr, t, "DEF-5") == 0
        assert _lineage_file(t, "DEF-5").is_file(), "the strike removed the middle row's lineage file"
        rc, out = _lineage(lr, t, "DEF-6", capsys)
        assert rc == 0
        assert "chain, child to root: DEF-6 -> DEF-5 -> DEF-1" in out, out

    @_BOTH_MODES
    def test_an_unknown_parent_is_refused_and_nothing_is_written(self, lr, tmp_path, opted_in, capsys):
        """Dies to: the parent's existence check dropped (a typo records a
        chain through no row)."""
        t = _tree(tmp_path, opted_in=opted_in)
        before = _snapshot(tmp_path)
        assert _file(lr, t, "DEF-5", "DEF-1", "DEF-77") == 2
        assert "--sibling-of DEF-77 names no row in the ledger" in capsys.readouterr().err
        assert _snapshot(tmp_path) == before

    def test_a_struck_parent_is_a_parent(self, lr, tmp_path):
        """Dies to: the existence check reading live rows only, which refuses
        the sibling of a row its lane just closed (the commonest case)."""
        t = _tree(tmp_path, opted_in=True)
        assert _strike(lr, t, "DEF-1") == 0
        assert _file(lr, t, "DEF-5", "DEF-1") == 0
        assert _lineage_file(t, "DEF-5").is_file()

    def test_the_row_itself_is_refused_as_its_own_parent(self, lr, tmp_path, capsys):
        t = _tree(tmp_path, opted_in=True)
        assert _file(lr, t, "DEF-5", "DEF-5") == 2
        assert "names the row being filed" in capsys.readouterr().err
        assert not _lineage_file(t, "DEF-5").exists()

    def test_a_leftover_lineage_file_with_no_row_is_refused(self, lr, tmp_path, capsys):
        """A lineage file for an id with no row is no filing's: overwriting it
        would hide a hand edit or another seat's write."""
        t = _tree(tmp_path, opted_in=True)
        _lineage_file(t, "DEF-5").parent.mkdir()
        _lineage_file(t, "DEF-5").write_text('{"id": "DEF-5", "sibling_of": ["DEF-2"]}\n', encoding="utf-8")
        assert _file(lr, t, "DEF-5", "DEF-1") == 2
        assert "already has a lineage file" in capsys.readouterr().err

    @_BOTH_MODES
    def test_a_lineage_path_that_cannot_be_a_directory_refuses_with_nothing_written(
            self, lr, tmp_path, opted_in, capsys):
        """Dies to: the lineage directory made at its own write, after the
        row's, which leaves a row with no probe and a traceback (code review)."""
        t = _tree(tmp_path, opted_in=opted_in)
        _lineage_file(t, "DEF-5").parent.write_text("not a directory\n", encoding="utf-8")
        before = _snapshot(tmp_path)
        assert _file(lr, t, "DEF-5", "DEF-1") == 2
        assert "the lineage directory" in capsys.readouterr().err
        assert _snapshot(tmp_path) == before

    def test_a_dry_run_names_the_lineage_file_and_writes_nothing(self, lr, tmp_path, capsys):
        t = _tree(tmp_path, opted_in=True)
        before = _snapshot(tmp_path)
        assert _file(lr, t, "DEF-5", "DEF-1", pre=("--dry-run",)) == 0
        assert "(its lineage as lineage.d/DEF-5.json: a sibling of DEF-1)" in capsys.readouterr().out
        assert _snapshot(tmp_path) == before


class TestAFilingCutBeforeItsProbeFinishesItsLineage:
    """The lineage file goes after the row and before the probe, so a filing
    cut anywhere before its probe is finished by running it again: the re-run
    writes a missing lineage file, keeps one that names the same parents, and
    refuses one that names others."""

    @staticmethod
    def _cut_at(lr, monkeypatch, dirname: str):
        gen = lr._load("generate_ledger_regions")
        real = gen._atomic_write

        def write(path, text):
            if Path(path).parent.name == dirname:
                raise OSError(28, "No space left on device")
            return real(path, text)

        monkeypatch.setattr(lr, "_load", lambda name, alias=None, _real=lr._load: gen if name ==
                            "generate_ledger_regions" else _real(name, alias))
        monkeypatch.setattr(gen, "_atomic_write", write)
        return lambda: monkeypatch.setattr(gen, "_atomic_write", real)

    @_BOTH_MODES
    def test_a_filing_cut_at_its_lineage_file_is_finished_with_it(self, lr, tmp_path, monkeypatch, opted_in):
        """Dies to: the lineage file written after the probe (the re-run then
        meets a whole filing and refuses it), or a finishing filing that
        writes the probe alone."""
        t = _tree(tmp_path, opted_in=opted_in)
        heal = self._cut_at(lr, monkeypatch, "lineage.d")
        with pytest.raises(OSError):
            _file(lr, t, "DEF-5", "DEF-1")
        heal()
        assert not _lineage_file(t, "DEF-5").exists()
        assert _file(lr, t, "DEF-5", "DEF-1") == 0
        assert json.loads(_lineage_file(t, "DEF-5").read_text(encoding="utf-8"))["sibling_of"] == ["DEF-1"]

    def test_a_filing_cut_at_its_probe_keeps_its_lineage_and_refuses_other_parents(
            self, lr, tmp_path, monkeypatch, capsys):
        """Dies to: a finishing filing that rewrites the lineage file it finds,
        or takes other parents for the same filing."""
        t = _tree(tmp_path, opted_in=True)
        heal = self._cut_at(lr, monkeypatch, "probes.d")
        with pytest.raises(OSError):
            _file(lr, t, "DEF-5", "DEF-1")
        heal()
        kept = _lineage_file(t, "DEF-5").read_bytes()
        capsys.readouterr()
        assert _file(lr, t, "DEF-5", "DEF-2") == 2
        assert "its lineage file names DEF-1 where these arguments give DEF-2" in capsys.readouterr().err
        assert _file(lr, t, "DEF-5", "DEF-1") == 0
        assert _lineage_file(t, "DEF-5").read_bytes() == kept
        assert (t["ledger"].parent / "probes.d" / "DEF-5.json").is_file()


class TestTheChainAdvisory:
    """At filing with ``--sibling-of``: recording-only by default, one line
    with the count; with the print on, the chain, the parents' children, the
    root's site family and the five questions when the new row is a sibling
    of a sibling or a parent's third child. stderr, exit 0, never a refusal."""

    def test_the_default_prints_the_one_recording_only_line(self, lr, tmp_path, capsys):
        """Dies to: the print's default flipped on, which shows a filer what
        would fire while the data the threshold review reads is gathered."""
        t = _tree(tmp_path, opted_in=True)
        assert _file(lr, t, "DEF-5", "DEF-1") == 0
        capsys.readouterr()
        assert _file(lr, t, "DEF-6", "DEF-5") == 0       # a grandchild: it would fire
        err = capsys.readouterr().err
        lines = [ln for ln in err.splitlines() if "chain advisory" in ln]
        assert lines == ["ledger_row: chain advisory: recording-only until 20 rows carry --sibling-of (2 now), "
                         "so what it prints does not shape what is filed"], err
        assert "child to root" not in err and lr.FIVE_QUESTIONS[0] not in err

    def test_at_the_recording_figure_the_line_says_the_review_is_due(self, lr, tmp_path, monkeypatch, capsys):
        t = _tree(tmp_path, opted_in=True)
        monkeypatch.setattr(lr, "CHAIN_RECORDING_UNTIL", 2)
        assert _file(lr, t, "DEF-5", "DEF-1") == 0
        assert "(1 now)" in capsys.readouterr().err
        assert _file(lr, t, "DEF-6", "DEF-1") == 0
        err = capsys.readouterr().err
        assert ("chain advisory: recording-only; 2 rows carry --sibling-of, enough to review its thresholds "
                "(CHAIN_DEPTH_AT, CHAIN_FAN_OUT_AT); CHAIN_ADVISORY_PRINTS in ledger_row.py turns the full "
                "print on") in err, err
        assert "child to root" not in err

    def test_with_the_print_on_a_grandchild_fires_in_a_dry_run(self, lr, tmp_path, monkeypatch, capsys):
        """Dies to: depth read from the immediate parent only, which calls a
        sibling of a sibling depth 1."""
        t = _tree(tmp_path, opted_in=True)
        monkeypatch.setattr(lr, "CHAIN_ADVISORY_PRINTS", True)
        assert _file(lr, t, "DEF-5", "DEF-1") == 0
        assert "chain advisory" not in capsys.readouterr().err, "a first sibling fired"
        before = _snapshot(tmp_path)
        assert _file(lr, t, "DEF-6", "DEF-5", pre=("--dry-run",)) == 0
        err = capsys.readouterr().err
        assert "chain advisory: DEF-6 extends a chain (depth 2, a sibling of a sibling)" in err, err
        assert "chain, child to root: DEF-6 -> DEF-5 -> DEF-1" in err
        assert "DEF-5's children: DEF-6" in err
        assert all(q in err for q in lr.FIVE_QUESTIONS)
        assert _snapshot(tmp_path) == before

    def test_with_the_print_on_a_third_child_fires_on_fan_out(self, lr, tmp_path, monkeypatch, capsys):
        """Dies to: fan-out counted without the new row."""
        t = _tree(tmp_path, opted_in=True)
        monkeypatch.setattr(lr, "CHAIN_ADVISORY_PRINTS", True)
        assert _file(lr, t, "DEF-5", "DEF-1") == 0 and _file(lr, t, "DEF-6", "DEF-1") == 0
        assert "chain advisory" not in capsys.readouterr().err
        assert _file(lr, t, "DEF-7", "DEF-1") == 0
        err = capsys.readouterr().err
        assert "chain advisory: DEF-7 extends a chain (DEF-1 has 3 children)" in err, err
        assert "DEF-1's children: DEF-5, DEF-6, DEF-7" in err

    def test_an_unreadable_lineage_file_is_a_note_never_a_refusal(self, lr, tmp_path, capsys):
        t = _tree(tmp_path, opted_in=True)
        _lineage_file(t, "DEF-9").parent.mkdir()
        _lineage_file(t, "DEF-9").write_text("{not json", encoding="utf-8")
        assert _file(lr, t, "DEF-5", "DEF-1") == 0
        err = capsys.readouterr().err
        assert "note -- a lineage file left out: task-packs/lineage.d/DEF-9.json: not JSON" in err, err
        assert "(1 now)" in err


class TestTheClusterAdvisory:
    """At a filing into the standalone class: the live standalone rows on the
    new row's site family, the new row counted; at five, a class may be
    waiting, with the five questions. stderr, exit 0, never a refusal."""

    @_BOTH_MODES
    def test_the_fifth_row_on_one_family_fires_in_a_dry_run(self, lr, tmp_path, opted_in, capsys):
        """Dies to: counting without the new row (four rows plus this one
        is five)."""
        t = _tree(tmp_path, opted_in=opted_in, c0_rows=_C0_ROWS)
        before = _snapshot(tmp_path)
        assert _file(lr, t, "DEF-20", section="C0", after="DEF-15", anchor=f"{_GUARD}::g",
                     pre=("--dry-run",)) == 0
        err = capsys.readouterr().err
        assert "cluster advisory: this is live standalone row 5 on tools:write_guard" in err, err
        assert "  the others: DEF-10, DEF-11, DEF-12, DEF-13" in err
        assert all(q in err for q in lr.FIVE_QUESTIONS)
        assert err.rstrip().endswith(lr.FIVE_QUESTIONS[-1]), "the advisory ends on the class verb, not the questions"
        assert _snapshot(tmp_path) == before

    def test_mixed_families_do_not_fire(self, lr, tmp_path, capsys):
        """Dies to: keying on the class instead of the family, which counts
        every live standalone row (seven here)."""
        t = _tree(tmp_path, opted_in=True, c0_rows=_C0_ROWS)
        assert _file(lr, t, "DEF-20", section="C0", after="DEF-15", anchor="espalier/cli.py::g") == 0
        assert "cluster advisory" not in capsys.readouterr().err

    def test_a_struck_row_is_not_counted(self, lr, tmp_path, capsys):
        t = _tree(tmp_path, opted_in=True, c0_rows=_C0_ROWS)
        assert _strike(lr, t, "DEF-13") == 0
        capsys.readouterr()
        assert _file(lr, t, "DEF-20", section="C0", after="DEF-15", anchor=f"{_GUARD}::g") == 0
        assert "cluster advisory" not in capsys.readouterr().err

    def test_a_site_with_no_path_says_why_once(self, lr, tmp_path, capsys):
        t = _tree(tmp_path, opted_in=True, c0_rows=_C0_ROWS)
        assert _file(lr, t, "DEF-20", section="C0", after="DEF-15", anchor="the release notes") == 0
        err = capsys.readouterr().err
        assert err.count("cluster advisory") == 1 and "counted on no site family" in err, err

    def test_a_classed_filing_prints_no_cluster_advisory(self, lr, tmp_path, capsys):
        t = _tree(tmp_path, opted_in=True, c0_rows=_C0_ROWS)
        assert _file(lr, t, "DEF-20", anchor=f"{_GUARD}::g") == 0
        assert "cluster advisory" not in capsys.readouterr().err


class TestTheLineageVerb:
    """``lineage <id>``: the row's chain to its root, the children, its site
    family's standalone count, and the five questions at a threshold. No lock,
    nothing written, exit 0 on every id."""

    def test_on_the_leaf_of_a_three_row_chain_it_prints_the_root_and_the_questions(self, lr, tmp_path, capsys):
        """Dies to: the chain read from the immediate parent only, which stops
        at DEF-5 and never reaches the root."""
        t = _tree(tmp_path, opted_in=True)
        assert _file(lr, t, "DEF-5", "DEF-1") == 0 and _file(lr, t, "DEF-6", "DEF-5") == 0
        before = _snapshot(tmp_path)
        rc, out = _lineage(lr, t, "DEF-6", capsys)
        assert rc == 0
        assert out.splitlines()[0].startswith("DEF-6: depth 2"), out
        assert "chain, child to root: DEF-6 -> DEF-5 -> DEF-1" in out
        assert all(q in out for q in lr.FIVE_QUESTIONS)
        assert _snapshot(tmp_path) == before

    def test_on_a_root_it_names_its_children_without_the_questions(self, lr, tmp_path, capsys):
        t = _tree(tmp_path, opted_in=True)
        assert _file(lr, t, "DEF-5", "DEF-1") == 0
        rc, out = _lineage(lr, t, "DEF-1", capsys)
        assert rc == 0 and "DEF-1's own children: DEF-5" in out, out
        assert lr.FIVE_QUESTIONS[0] not in out

    def test_a_row_at_the_cluster_figure_prints_the_questions(self, lr, tmp_path, capsys):
        t = _tree(tmp_path, opted_in=True, c0_rows=_C0_ROWS)
        assert _file(lr, t, "DEF-20", section="C0", after="DEF-15", anchor=f"{_GUARD}::g") == 0
        rc, out = _lineage(lr, t, "DEF-10", capsys)
        assert rc == 0 and "site family tools:write_guard, 5 live standalone row(s) on it" in out, out
        assert all(q in out for q in lr.FIVE_QUESTIONS)

    def test_a_row_with_neither_is_one_line_saying_why_once(self, lr, tmp_path, capsys):
        """Dies to: "no recorded lineage" printed alike on a tree where no
        filer has passed the flag yet, which a planner reads as "not in a
        chain" (failure-mode review)."""
        t = _tree(tmp_path, opted_in=True)
        rc, out = _lineage(lr, t, "DEF-2", capsys)
        assert rc == 0
        assert out.splitlines() == ["DEF-2: no recorded lineage (no row on this tree carries --sibling-of yet); "
                                    "its site cell names no path, so no site family"], out
        assert _file(lr, t, "DEF-5", "DEF-1") == 0
        rc, out = _lineage(lr, t, "DEF-2", capsys)
        assert out.splitlines() == ["DEF-2: no recorded lineage (it names no parent and no row names it); "
                                    "its site cell names no path, so no site family"], out

    def test_a_struck_row_on_a_cluster_family_prints_no_questions(self, lr, tmp_path, capsys):
        """Dies to: the cluster's questions printed for a struck row, which a
        pack cites as history and no plan will fix (failure-mode review: one
        pack's ids printed them 24 times, 22 for struck rows)."""
        t = _tree(tmp_path, opted_in=True, c0_rows=_C0_ROWS)
        assert _file(lr, t, "DEF-20", section="C0", after="DEF-15", anchor=f"{_GUARD}::g") == 0
        assert _file(lr, t, "DEF-21", section="C0", after="DEF-15", anchor=f"{_GUARD}::h") == 0
        assert _strike(lr, t, "DEF-10") == 0
        rc, out = _lineage(lr, t, "DEF-10", capsys)
        assert rc == 0 and "5 live standalone row(s) on it" in out, out
        assert lr.FIVE_QUESTIONS[0] not in out
        rc, out = _lineage(lr, t, "DEF-11", capsys)
        assert lr.FIVE_QUESTIONS[0] in out, out

    def test_a_root_with_no_row_here_is_named_and_reported(self, lr, tmp_path, capsys):
        """Dies to: a root the ledger no longer holds reported as a row whose
        site names no path, and the root itself as an id nothing names."""
        t = _tree(tmp_path, opted_in=True)
        assert _file(lr, t, "DEF-5", "DEF-1") == 0
        text = t["ledger"].read_text(encoding="utf-8")
        t["ledger"].write_text("\n".join(ln for ln in text.split("\n") if not ln.startswith("| `DEF-1` |")),
                               encoding="utf-8")
        rc, out = _lineage(lr, t, "DEF-5", capsys)
        assert rc == 0 and "the root's site family: none (the root has no row in this ledger)" in out, out
        rc, out = _lineage(lr, t, "DEF-1", capsys)
        assert rc == 0 and "no row in this ledger, though a lineage file names it" in out, out
        assert "DEF-1's own children: DEF-5" in out

    def test_an_id_in_no_row_is_one_line_and_exit_0(self, lr, tmp_path, capsys):
        t = _tree(tmp_path, opted_in=False)
        rc, out = _lineage(lr, t, "DEF-404", capsys)
        assert rc == 0 and out.splitlines() == [
            "DEF-404: no row in the ledger, live or struck, carries this id; nothing to report"]

    def test_it_takes_no_lock(self, lr, tmp_path, capsys):
        """Dies to: the verb dispatched under the ledger lock, where a filing in
        flight on another seat's checkout would refuse a plan its read."""
        t = _tree(tmp_path, opted_in=True)
        with lr._GEN.ledger_lock(t["ledger"]):
            rc, out = _lineage(lr, t, "DEF-1", capsys)
        assert rc == 0 and out.startswith("DEF-1: "), out

    def test_a_tree_with_no_ledger_is_one_line_and_exit_0(self, lr, tmp_path, capsys):
        capsys.readouterr()
        assert lr.main(["--root", str(tmp_path), "lineage", "DEF-1"]) == 0
        assert "no ledger at" in capsys.readouterr().out


class TestTheSiteFamily:
    """The key both the cluster advisory and the verb count by."""

    @pytest.mark.parametrize("site, family", [
        ("tools/cc/hooks/write_guard.py::f", "tools:write_guard"),
        ("tools\\cc\\hooks\\write_guard.py", "tools:write_guard"),
        ("espalier/cli.py::_x and `docs/A.md`", "espalier:cli"),
        ("CLAUDE.md row 12", ".:CLAUDE"),
        (".pre-commit-config.yaml's hook list", ".:.pre-commit-config.yaml"),
        (".github/workflows/test.yml", ".github:test"),
        ("scripts/census/ (the whole folder)", "scripts:census"),
        ("the release notes", None),
    ])
    def test_each_shape(self, lr, site, family):
        assert lr.site_family(site) == family

    def test_the_first_path_wins_over_one_in_a_span(self, lr):
        """Dies to: a backtick span read first, which keys a row on a path it
        only mentions (six of this tree's 113 live standalone rows, measured
        2026-11-12)."""
        assert lr.site_family("scripts/derived.py::_bind (iterates `tree.body` only)") == "scripts:derived"


class TestTheFiveQuestions:
    def test_they_are_five_numbered_ascii_lines_with_no_internal_ids(self, lr):
        """The constant deploys with the verb: an id or a section sign in it
        points an adopter at a record it does not have."""
        import re

        assert [q.split(".", 1)[0] for q in lr.FIVE_QUESTIONS] == ["1", "2", "3", "4", "5"]
        for q in lr.FIVE_QUESTIONS:
            assert q.isascii(), q
            assert not re.search(r"\b[A-Z]{2,5}-\d+", q), q

    @pytest.mark.contract
    def test_the_memory_note_quotes_each_question_word_for_word_in_order(self, lr):
        """The note holds the questions' fuller wording and the constant the
        text a tree prints, so the two drift apart unless one quotes the
        other: each constant line is in the note word for word, numbered, in
        order, once its markdown emphasis and line wraps are read as plain
        text. Dies to: a word of one constant line changed, a question
        dropped from the note, two questions swapped."""
        import re

        note = (REPO_ROOT / "memory" / "check-the-layer-before-the-class.md").read_text(encoding="utf-8")
        plain = re.sub(r"\s+", " ", note.replace("**", ""))
        at = [plain.find(q) for q in lr.FIVE_QUESTIONS]
        assert -1 not in at, [q for q, i in zip(lr.FIVE_QUESTIONS, at) if i == -1]
        assert at == sorted(at), "the note lists the questions in another order"


def _plain(rel: str) -> str:
    """``rel``'s text with markdown emphasis and line wraps read as plain text."""
    import re

    return re.sub(r"\s+", " ", (REPO_ROOT / rel).read_text(encoding="utf-8").replace("**", ""))


@pytest.mark.contract
class TestTheLayerQuestionsReachTheirReaders:
    """The hops a parent id and the questions travel, each pinned where a
    reviewer of this lane found it could silently break."""

    def test_the_handoff_writes_a_sibling_finding_into_the_row_every_seat_writes(self):
        """A seat with no goal doc skips the goal step, so a sentence there
        never reaches a worker seat's handoff. Dies to: the sentence moved
        back out of the session-row step."""
        text = _plain(".claude/commands/handoff.md")
        row_step = text.split("## 2. Write the session row", 1)[1].split("## 3.", 1)[0]
        assert "(sibling of DEF-N)" in row_step and "--sibling-of DEF-N" in row_step

    def test_the_class_note_sends_its_reader_to_the_layer_note_first(self):
        """Core Rule 12 names the class note its sole home. Dies to: the
        class note's pointer to the layer questions removed."""
        assert "[[check-the-layer-before-the-class]]" in _plain("memory/fix-the-class-not-the-instance.md")

    def test_the_note_says_what_the_chain_advisory_prints_today(self, lr):
        """Dies to: the full chain print turned on while the note still
        calls the advisory recording-only, or the reverse."""
        says_recording = "chain advisory is recording-only" in _plain("memory/check-the-layer-before-the-class.md")
        assert says_recording is (not lr.CHAIN_ADVISORY_PRINTS)
