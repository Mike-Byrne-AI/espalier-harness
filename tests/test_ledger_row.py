"""Contract tests for ``tools/cc/ledger_row.py`` on a fixture ledger.

The ledger had no git undo until 2026-09-21 (it was gitignored), and a wrong
strike still deletes live work; these tests exist because the helper rewrites that file. They pin that
a strike keeps PRIOR TEXT, strikes the index row, retires the probe and leaves
the regions converged; that a filing drives its probe FIRST and writes nothing
when the probe does not print the open value; that the recorded row_sha is
the one ``check_ledger_probes`` recomputes; that a row shape the splitter
cannot round-trip is refused rather than mangled; and that a refused write
touches neither file; that the roster stores no total (a ``_count`` left
from before 2026-10-12 is read and dropped by every writer, and
``--reconcile-count`` is still accepted and does nothing); that ``repin`` drives the probe first, rewrites only what it was
asked to, and stamps the sha the checker recomputes; and that a missing probe
file is created for a ledger with no live row and refused beside live rows.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_generate_ledger_regions import _ledger

# slow-exempt: one test drives the verb as a child process under a cp1252
# stdout (measured 0.2s) -- the failure is the real stream, so only the real
# CLI can show it.

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "cc" / "ledger_row.py"


def _load():
    spec = importlib.util.spec_from_file_location("ledger_row", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def lr():
    return _load()


@pytest.fixture(autouse=True)
def _away_from_the_live_tree(tmp_path, monkeypatch):
    """A verb run without ``--root`` finds its root by walking up from the
    working directory, and from here that is this checkout: its
    ``espalier.toml [id_blocks]`` and its machine name would then govern a
    fixture's ids (tests/CLAUDE.md, rule 4). Each test starts in its own."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def tree(tmp_path):
    return _build_tree(tmp_path)


def _build_tree(tmp_path: Path) -> dict:
    packs = tmp_path / "task-packs"
    packs.mkdir()
    ledger = packs / "FORWARD_LEDGER.md"
    ledger.write_text(_ledger(), encoding="utf-8")
    probes = packs / "LEDGER_PROBES.json"
    probes.write_text(json.dumps({
        "probes": [
            {"id": "DEF-1", "subject": "site", "cmd": "echo a", "open_value": "a", "why_not": None, "row_sha": "x"},
            {"id": "DEF-2", "subject": "site", "cmd": "echo b", "open_value": "b", "why_not": None, "row_sha": "y"},
        ],
    }, indent=1) + "\n", encoding="utf-8")
    closing = tmp_path / "closing.md"
    closing.write_text("landed in abc123 after one pass\nof each red team", encoding="utf-8")
    body = tmp_path / "body.md"
    body.write_text("**A new defect.** Who: an adopter.", encoding="utf-8")
    return {"ledger": ledger, "probes": probes, "closing": closing, "body": body}


def _args(tree, *rest):
    return ["--ledger", str(tree["ledger"]), "--probes", str(tree["probes"]),
            "--date", "2026-09-06", *rest]


def _closed(tree, *ids: str) -> None:
    """The lane fixed what ``ids`` name: each row's probe no longer prints its
    open value, which the strike's head drive requires since 2026-10-25 (a
    probe still printing it is the refusal ``TestAStrikeReadsTheBaseAndTheHead``
    pins). A fixture probe is an ``echo``, so its command is the one lever."""
    data = json.loads(tree["probes"].read_text(encoding="utf-8"))
    for probe in data["probes"]:
        if probe.get("id") in ids:
            probe["cmd"] = "echo closed"
    tree["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


def _derived(lr, text: str) -> tuple[int, int, list]:
    """``(live total, §C1's member rows, stored totals)``. Derived: the ledger
    stores no total, so a verb's work is read from its rows, and the third
    item is empty on every ledger a verb leaves."""
    gen = lr._load("generate_ledger_regions")
    d = gen.derive(text)
    return d["live_total"], d["sections"].get("§C1", 0), gen.stored_counts(text)


def _tally(lr, text: str) -> dict[str, int]:
    """Every live population and audience figure, derived, in one dict (the
    two vocabularies are disjoint)."""
    d = lr._load("generate_ledger_regions").derive(text)
    return {**d["population_live"], **d["audience_live"]}


class TestStrike:
    def test_strike_keeps_prior_text_strikes_the_index_and_retires_the_probe(self, lr, tree):
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert ("| ~~`DEF-1`~~ | site | ✅ **CLOSED 2026-09-06 — landed in abc123 after one pass "
                "of each red team** PRIOR TEXT: what | major |") in text
        assert "| ~~`DEF-1`~~ | §C1 | site |" in text
        assert _derived(lr, text) == (1, 2, [])
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        assert [p["id"] for p in data["probes"]] == ["DEF-2"] and "_count" not in data
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(text) == []

    def test_a_struck_or_unknown_row_is_refused(self, lr, tree, capsys):
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2
        assert "no unstruck member row" in capsys.readouterr().err
        assert lr.main(_args(tree, "strike", "DEF-9", "--text-file", str(tree["closing"]))) == 2

    def test_an_escaped_pipe_round_trips_and_an_unescaped_one_is_refused(self, lr, tree, capsys):
        """The real ledger escapes a literal pipe as `\\|`; one row does not, and
        one table has three cells. The first cut's split moved 1,194 characters
        of a real row into its severity column and raised on 28 others."""
        rows = (
            "| `DEF-1` | site | what with `a \\| b` inside | major |",
            "| `DEF-2` | site | what | unescaped | minor |",
        )
        tree["ledger"].write_text(_ledger(c1_rows=rows), encoding="utf-8")
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "strike", "DEF-2", "--text-file", str(tree["closing"]))) == 2
        assert "5 cells, not 4" in capsys.readouterr().err
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "PRIOR TEXT: what with `a \\| b` inside | major |" in text

    def test_a_three_cell_row_from_another_table_is_refused(self, lr, tree, capsys):
        tree["ledger"].write_text(_ledger(c1_rows=("| `DEF-1` | decision text | open |",
                                                   "| `DEF-2` | site | what | minor |")), encoding="utf-8")
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2
        assert "3 cells, not 4" in capsys.readouterr().err

    def test_a_refused_strike_writes_neither_file(self, lr, tree, monkeypatch, capsys):
        """Atomicity: the first cut retired the probe before checking
        convergence, leaving an open row with no probe when the strike was
        refused (failure-mode pass, driven)."""
        monkeypatch.setattr(lr, "_converge",
                            lambda gen, text, probes_path, pending=None: (text, [{"region": "x", "detail": "forced"}]))
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2
        assert "nothing written" in capsys.readouterr().err
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before
        assert not list(tree["probes"].parent.glob("*.pending"))

    def test_dry_run_writes_nothing(self, lr, tree, capsys):
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        assert "PRIOR TEXT: what" in capsys.readouterr().out
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before


    def test_a_stale_count_never_refuses_a_strike_and_the_old_flag_still_parses(self, lr, tree, capsys):
        """The roster stores no total, so a ``_count`` left from before
        2026-10-12 disagrees with nothing: the strike runs and drops the key.
        ``--reconcile-count`` (which accepted the mismatch the verbs refused
        until then) is still accepted, so an old command line runs. The hand
        edit the count used to witness is the probe runner's to name now: it
        compares the ledger's live rows against the roster's entries."""
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        data["_count"] = 99
        tree["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        assert "_count" not in capsys.readouterr().err
        assert lr.main(_args(tree, "--reconcile-count", "strike", "DEF-2",
                             "--text-file", str(tree["closing"]))) == 0
        after = json.loads(tree["probes"].read_text(encoding="utf-8"))
        assert after["probes"] == [] and "_count" not in after

class TestADeferralIntoTheStruckRow:
    """DEF-412a: a strike reads the in-flight packs' ``## Scope (out)`` first.

    Origin: TP-371 landed one member of the old §2.3 and parked its ~47 sibling
    read sites in its own Scope (out) as "a §2.3 remainder"; nothing mechanical
    read that sentence, so the landed-so-strike-it convention could take the
    section, remainder and all, with no git undo on a then-gitignored ledger.
    The population is the two shipped locations -- the ``task-packs/`` root and
    ``Deferred/`` -- and never ``Done/``: a landed pack's citation is history,
    not a deferral. Every row here runs on the fixture ledger under tmp_path;
    the live tree is never read.
    """

    @staticmethod
    def _pack(tree, rel: str, scope_out: str, before: str = "") -> Path:
        path = tree["ledger"].parent / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# TP stub\n\n## Status\n- State: DRAFT\n{before}\n## Scope (out)\n{scope_out}\n"
            "## Implementation\n\nunrelated\n", encoding="utf-8")
        return path

    def test_a_root_pack_deferring_into_the_row_refuses_and_writes_nothing(self, lr, tree, capsys):
        self._pack(tree, "TP-9-x.md", "- the rest waits on `DEF-1` (deferred)\n")
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2
        err = capsys.readouterr().err
        assert "TP-9-x.md" in err and "DEF-1" in err and "--despite-deferrals" in err
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before
        # the dry run reports the same refusal rather than a row it would never write
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2

    def test_despite_deferrals_strikes_under_an_advisory(self, lr, tree, capsys):
        self._pack(tree, "TP-9-x.md", "- the rest waits on `DEF-1` (deferred)\n")
        assert lr.main(_args(tree, "strike", "DEF-1", "--despite-deferrals",
                             "--text-file", str(tree["closing"]))) == 0
        err = capsys.readouterr().err
        assert "TP-9-x.md" in err and "despite" in err
        assert "| ~~`DEF-1`~~ |" in tree["ledger"].read_text(encoding="utf-8")

    def test_a_deferred_pack_is_population_and_a_done_pack_is_not(self, lr, tree, capsys):
        self._pack(tree, "Done/TP-8-landed.md", "- `DEF-1` stays open (deferred)\n")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        self._pack(tree, "Deferred/TP-7-parked.md", "- `DEF-1` stays open (deferred)\n")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2
        assert "Deferred/TP-7-parked.md" in capsys.readouterr().err

    def test_a_citation_outside_scope_out_is_ownership_not_deferral(self, lr, tree):
        # A roadmap lists the rows its lanes will strike in its Reach and
        # Implementation; reading the whole pack would refuse every strike that
        # roadmap exists to make. (TP-449 also PARKS twelve rows in its Scope
        # (out) for its own later tiers -- all pre-rebuild ids today, so inert --
        # and those ARE refused until the pack records the tier: the refusal
        # says so. Scope (out) only, and only there.)
        self._pack(tree, "TP-9-x.md", "- nothing deferred\n",
                   before="## Reach\n- `DEF-1` closed by lane 1\n")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0

    def test_an_id_is_matched_whole(self, lr, tree):
        # `DEF-1a` is a different row; striking `DEF-1` must not read it as a deferral.
        self._pack(tree, "TP-9-x.md", "- `DEF-1a` deferred\n")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0

    def test_a_section_number_in_scope_out_is_not_read(self, lr, tree):
        # Class numbers were reissued at the 2026-09-20 rebuild, so `§C1` in a
        # pack authored before it names the OLD §C1; the structural cut owns
        # section removal. The first cut refused the strike that emptied a cited
        # section and would have fired on a stale number (failure-mode pass).
        self._pack(tree, "TP-9-x.md", "- the remainder is a §C1 remainder\n")
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-2", "--text-file", str(tree["closing"]))) == 0

    def test_a_bare_tail_inside_a_backticked_list_is_read_and_a_lone_number_is_not(self, lr, tree, capsys):
        # TP-452 parks eleven rows as "(`736, 424b, 516, PR-3, 6,\n  451`)"; the
        # first cut read one of them (both reviewers, 2026-09-21). The list may
        # cross a line break; a lone backticked number is a count, not a row.
        self._pack(tree, "TP-9-x.md", "- the demoted rows (`7, 1,\n  9`) hold\n")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2
        assert "[cites DEF-1]" in capsys.readouterr().err
        self._pack(tree, "TP-9-x.md", "- `1` row is left, and `x, 1` is prose\n")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0

    def test_a_fenced_block_inside_scope_out_is_not_read(self, lr, tree):
        # A fenced shell snippet's `# comment` is not a heading and its `DEF-1`
        # is not a citation (code review, 2026-09-21; latent on the live packs).
        self._pack(tree, "TP-9-x.md", "```bash\n# note\necho DEF-1\n```\n- nothing deferred\n")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0

    def test_one_line_citing_both_ids_of_a_two_id_row_is_one_hit(self, lr, tree, capsys):
        tree["ledger"].write_text(_ledger(c1_rows=("| `DEF-1` `LG-9` | site | what | major |",
                                                   "| `DEF-2` | site | what | minor |")), encoding="utf-8")
        self._pack(tree, "TP-9-x.md", "- `DEF-1` and `LG-9` wait on the walk\n")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2
        err = capsys.readouterr().err
        assert "1 Scope (out) line(s)" in err and "[cites DEF-1, LG-9]" in err

    def test_strike_anchor_re_points_the_index_row_too(self, lr, tree):
        # DEF-648's strike re-pointed the member anchor and left the index row
        # citing three moved paths (code review, 2026-09-21).
        assert lr.main(_args(tree, "strike", "DEF-1", "--anchor", "new::home",
                             "--text-file", str(tree["closing"]))) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "| ~~`DEF-1`~~ | new::home | ✅ **CLOSED 2026-09-06" in text
        assert "| ~~`DEF-1`~~ | §C1 | new::home |" in text


class TestABaselinedIdRefusesTheStrike:
    """DEF-1172: a strike reads the probe test's per-id baselines first.

    `tests/test_check_ledger_probes.py` keeps hand-written tables over the live
    probes, each with a dead-entry check. The strike retired the probe and read
    nothing under tests/, so the struck id stayed and the next run collecting
    that check went red in a lane that never touched the file (DEF-940 on
    2026-09-29, DEF-884 on 2026-10-07). The tables are found by parsing, so
    each shape is driven on the fixture tree's own tests/ folder; the live tree
    is never read. Earn-the-red: against the pre-change module every refusal
    row below strikes."""

    @staticmethod
    def _tests_file(tree, body: str) -> Path:
        path = tree["ledger"].parents[1] / "tests" / "test_check_ledger_probes.py"
        path.parent.mkdir(exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    @staticmethod
    def _strike(lr, tree, rid: str = "DEF-1", *pre: str) -> int:
        return lr.main(_args(tree, *pre, "strike", rid, "--text-file", str(tree["closing"])))

    def test_a_baselined_id_refuses_by_line_and_writes_nothing(self, lr, tree, capsys):
        self._tests_file(tree, 'class TestTheLiveProbeFile:\n    _NAMED_NOT_READ = {\n'
                               '        "DEF-1": {"x"},\n    }\n')
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        assert self._strike(lr, tree) == 2
        err = capsys.readouterr().err
        assert "tests/test_check_ledger_probes.py:3: _NAMED_NOT_READ holds DEF-1" in err
        assert "Nothing written" in err
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before
        # the dry run shows the same refusal rather than a row it would never write
        assert self._strike(lr, tree, "DEF-1", "--dry-run") == 2

    def test_every_table_shape_is_read_and_each_id_named_on_its_own_line(self, lr, tree, capsys):
        self._tests_file(tree, (
            '_MODULE = frozenset({"DEF-1"})\n'
            '_LISTED = set(["DEF-0", "DEF-1"])\n'
            'class TestProbeShapesAreRatcheted:\n'
            '    _PACKED = {\n'
            '        "DEF-0", "DEF-7",\n'
            '        "DEF-8", "DEF-1",\n'
            '    }\n'
            '    _TYPED: dict = {"DEF-1": 1}\n'
        ))
        assert self._strike(lr, tree, "DEF-1", "--dry-run") == 2
        err = capsys.readouterr().err
        for want in (":1: _MODULE holds DEF-1", ":2: _LISTED holds DEF-1", ":6: _PACKED holds DEF-1",
                     ":8: _TYPED holds DEF-1"):
            assert want in err, err
        assert "4 id(s)" in err

    def test_an_argument_list_a_word_tuple_a_lowercase_name_or_a_local_is_not_a_table(self, lr, tree):
        self._tests_file(tree, (
            '_PARTIAL = ["--id", "DEF-1"]\n'
            '_WORDS = ("nearest", "DEF-1")\n'
            'fixture_ids = {"DEF-1"}\n'
            'def test_x():\n'
            '    LOCAL = {"DEF-1"}\n'
        ))
        assert self._strike(lr, tree) == 0
        assert "| ~~`DEF-1`~~ |" in tree["ledger"].read_text(encoding="utf-8")

    def test_an_unbaselined_strike_and_a_tree_with_no_tests_file_are_unchanged(self, lr, tree, capsys):
        assert self._strike(lr, tree, "DEF-2") == 0           # no tests/ at all: an adopter's tree
        self._tests_file(tree, '_NAMED_NOT_READ = {"DEF-9": {"x"}}\n')
        assert self._strike(lr, tree) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "| ~~`DEF-1`~~ |" in text and "| ~~`DEF-2`~~ |" in text
        assert "baselines" not in capsys.readouterr().err

    def test_a_probe_kept_as_its_own_file_is_read_as_retiring(self, lr, tree, capsys):
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        own = next(p for p in data["probes"] if p["id"] == "DEF-1")
        data["probes"] = [p for p in data["probes"] if p["id"] != "DEF-1"]
        tree["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        (tree["probes"].parent / "probes.d").mkdir()
        (tree["probes"].parent / "probes.d" / "DEF-1.json").write_text(json.dumps(own) + "\n", encoding="utf-8")
        self._tests_file(tree, '_NAMED_NOT_READ = {"DEF-1": {"x"}}\n')
        assert self._strike(lr, tree, "DEF-1", "--dry-run") == 2
        assert "_NAMED_NOT_READ holds DEF-1" in capsys.readouterr().err

    def test_a_row_whose_probe_is_not_retired_here_is_not_held(self, lr, tree):
        """Keyed on the probes this strike retires: a table over the live probes
        cannot gain a dead entry from a row that has none."""
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        data["probes"] = [p for p in data["probes"] if p["id"] != "DEF-2"]
        tree["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        self._tests_file(tree, '_NAMED_NOT_READ = {"DEF-2": {"x"}}\n')
        assert self._strike(lr, tree, "DEF-2") == 0

    def test_a_co_id_retiring_with_the_row_is_read_too(self, lr, tree, capsys):
        TestATwoIdRow()._two_id_tree(tree)
        self._tests_file(tree, '_SPAWNS_A_LITERAL_INTERPRETER = frozenset({"LG-9"})\n')
        assert self._strike(lr, tree, "DEF-1", "--dry-run") == 2
        assert ":1: _SPAWNS_A_LITERAL_INTERPRETER holds LG-9" in capsys.readouterr().err

    def test_a_file_that_does_not_parse_is_named_and_the_strike_proceeds(self, lr, tree, capsys):
        self._tests_file(tree, '_NAMED_NOT_READ = {"DEF-1": \n')
        assert self._strike(lr, tree) == 0
        assert "does not parse" in capsys.readouterr().err

    def test_the_struck_ledgers_own_tree_is_read_not_the_working_directorys(self, lr, tree, monkeypatch):
        """`--ledger` aimed at another checkout reads that checkout's tests, never
        the root a walk from the working directory finds (code review)."""
        here = tree["ledger"].parents[1] / "elsewhere"
        (here / "task-packs").mkdir(parents=True)
        (here / "task-packs" / "FORWARD_LEDGER.md").write_text(tree["ledger"].read_text(encoding="utf-8"),
                                                              encoding="utf-8")
        (here / "tests").mkdir()
        (here / "tests" / "test_check_ledger_probes.py").write_text('_NAMED_NOT_READ = {"DEF-1": {"x"}}\n',
                                                                   encoding="utf-8")
        monkeypatch.chdir(here)
        assert self._strike(lr, tree, "DEF-1", "--dry-run") == 0   # the working directory's table is not read
        self._tests_file(tree, '_NAMED_NOT_READ = {"DEF-1": {"x"}}\n')
        assert self._strike(lr, tree, "DEF-1", "--dry-run") == 2   # the struck ledger's own table is


class TestFile:
    def _file(self, lr, tree, *extra, pre=(), probe_cmd="echo open=True", open_value="open=True"):
        return lr.main(_args(
            tree, "--root", str(tree["ledger"].parents[1]), *pre,
            "file", "DEF-3", "--section", "C1", "--after", "DEF-2",
            "--anchor", "new/site.py::fn", "--text-file", str(tree["body"]), "--severity", "minor",
            "--probe-cmd", probe_cmd, "--open-value", open_value, "--subject", "body.md", *extra,
        ))

    def test_file_inserts_both_rows_adds_a_driven_probe_and_converges(self, lr, tree):
        assert self._file(lr, tree) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        member = "| `DEF-3` | new/site.py::fn | **A new defect.** Who: an adopter. | minor |"
        assert member in text and "| `DEF-3` | §C1 | new/site.py::fn |" in text
        assert text.index("| `DEF-2` | site") < text.index(member)
        assert _derived(lr, text) == (3, 3, [])
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        new = [p for p in data["probes"] if p["id"] == "DEF-3"][0]
        assert new["open_value"] == "open=True" and len(data["probes"]) == 3 and "_count" not in data
        # the sha check_ledger_probes recomputes: sha256 of the unstruck member line, first 12
        assert new["row_sha"] == hashlib.sha256(member.encode("utf-8")).hexdigest()[:12]
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(text) == []

    def test_both_files_are_written_with_lf_on_every_platform(self, lr, tree):
        """Measured 2026-09-28 on Windows: one `repin` rewrote the live ledger
        (1,922 lines) and the probes file with CRLF, because both writers called
        `write_text` without `newline`, and git warned on the next touch. The
        tracked files are LF; a verb must not re-line them. On a POSIX host this
        passes with or without the fix -- the sentinel is the Windows cell."""
        assert self._file(lr, tree) == 0
        for key in ("ledger", "probes"):
            assert b"\r\n" not in tree[key].read_bytes(), key

    def test_a_probe_that_does_not_print_its_open_value_files_nothing(self, lr, tree, capsys):
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        assert self._file(lr, tree, probe_cmd="echo open=False") == 2
        err = capsys.readouterr().err
        assert "does not print its open value 'open=True'" in err and "STRIKE_CANDIDATE" in err
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before

    def test_a_duplicate_id_is_refused(self, lr, tree):
        assert self._file(lr, tree) == 0
        assert self._file(lr, tree) == 2

    def test_file_writes_the_declared_inputs_after_driving_them(self, lr, tree, capsys):
        """`DEF-858`: a probe may read a path its subject does not name. The
        filing drives the probe through the runner's own inputs gate, so a
        declared path absent on this tree refuses it (nothing written) -- the
        same UNRESOLVED the recurring check would report there."""
        root = tree["ledger"].parents[1]
        before = tree["probes"].read_text(encoding="utf-8")
        assert self._file(lr, tree, "--inputs", "records/Done") == 2
        assert "input missing: records/Done" in capsys.readouterr().err
        assert tree["probes"].read_text(encoding="utf-8") == before
        (root / "records" / "Done").mkdir(parents=True)
        (root / "records" / "Done" / "TP-1-x.md").write_text("", encoding="utf-8")  # a bare dir is "input empty"
        assert self._file(lr, tree, "--inputs", "records/Done") == 0
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        by_id = {p["id"]: p for p in data["probes"]}
        assert by_id["DEF-3"]["inputs"] == ["records/Done"]
        # a row filed without the flag carries no key at all: the shape of every
        # existing entry is unchanged
        assert "inputs" not in by_id["DEF-1"]

    def test_file_refuses_inputs_on_a_row_declared_why_not(self, lr, tree, capsys):
        # `run_probe` returns NO_ORACLE before the inputs gate on a no-command
        # row, so the declaration would be written undriven (both reviewers,
        # 2026-09-22); `repin` refuses the same shape by name.
        before = tree["probes"].read_text(encoding="utf-8")
        with pytest.raises(SystemExit):
            lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]),
                          "file", "DEF-3", "--section", "C1", "--after", "DEF-2",
                          "--anchor", "new/site.py::fn", "--text-file", str(tree["body"]),
                          "--severity", "minor", "--subject", "body.md",
                          "--why-not", "no local oracle", "--inputs", "site"))
        assert "--inputs cannot be driven" in capsys.readouterr().err
        assert tree["probes"].read_text(encoding="utf-8") == before

    def test_the_probe_runs_from_root_with_the_checkers_timeout(self, lr, tree, tmp_path):
        """A probe accepted at filing must be one the recurring checker can run:
        same cwd (the repo root), same timeout (read from check_ledger_probes)."""
        marker = tmp_path / "root-marker.txt"
        marker.write_text("open=True", encoding="utf-8")
        rc = lr.main(_args(
            tree, "--root", str(tmp_path), "file", "DEF-5", "--section", "C1", "--after", "DEF-2",
            "--anchor", "a", "--text-file", str(tree["body"]), "--severity", "nit",
            "--probe-cmd", "cat root-marker.txt", "--open-value", "open=True",
            "--subject", "root-marker.txt",
        ))
        assert rc == 0
        # a subject that does not exist under --root is UNRESOLVED to the
        # checker, and therefore refused here too -- the same verdict, by
        # construction, not by a second implementation
        rc = lr.main(_args(
            tree, "--root", str(tmp_path), "file", "DEF-6", "--section", "C1", "--after", "DEF-2",
            "--anchor", "a", "--text-file", str(tree["body"]), "--severity", "nit",
            "--probe-cmd", "cat root-marker.txt", "--open-value", "open=True",
            "--subject", "no/such/file.py",
        ))
        assert rc == 2

    def test_why_not_files_without_a_probe_command(self, lr, tree):
        rc = lr.main(_args(
            tree, "file", "DEF-4", "--section", "C1", "--after", "DEF-2",
            "--anchor", "a", "--text-file", str(tree["body"]), "--severity", "nit",
            "--subject", "a", "--why-not", "no local oracle: needs the GitHub console",
        ))
        assert rc == 0
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        new = [p for p in data["probes"] if p["id"] == "DEF-4"][0]
        assert new["cmd"] is None and new["why_not"].startswith("no local oracle")

    def test_a_stale_count_never_refuses_a_filing_under_the_old_flag(self, lr, tree, capsys):
        """The filing twin: an old command line carrying ``--reconcile-count``
        over a roster with a stale ``_count`` files, and the key is gone."""
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        data["_count"] = 0
        tree["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        assert self._file(lr, tree, pre=("--reconcile-count",)) == 0
        err = capsys.readouterr().err
        # said, never silent: the flag reconciles nothing now (failure-mode review)
        assert "--reconcile-count does nothing" in err and "_count=" not in err
        after = json.loads(tree["probes"].read_text(encoding="utf-8"))
        assert len(after["probes"]) == 3 and "_count" not in after


def _two_lanes(tmp_path: Path, lane_a, lane_b) -> tuple[subprocess.CompletedProcess, Path]:
    """A base commit of the fixture tree, then each lane runs one real verb from
    the base on its own branch; returns GitHub's merge of the two (``merge-tree``
    with no ``.gitattributes``, so no merge driver) and the repository."""
    from tests._git_oracle import _git_env

    def git(*a: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=_git_env(), timeout=45)

    t = _build_tree(tmp_path)
    git("init", "-q", "-b", "main")
    for k, v in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
        git("config", k, v)
    git("add", "-A")
    git("commit", "-qm", "base")
    for branch, verb in (("a", lane_a), ("b", lane_b)):
        git("switch", "-q", "-c", branch, "main")
        assert verb(t) == 0
        git("commit", "-qam", branch)
    return git("merge-tree", "--write-tree", "--name-only", "--no-messages", "a", "b"), tmp_path


class TestProbesCountDerived:
    """The roster stores no total. Every verb re-derived ``_count`` on every
    write, so two lanes that each changed the roster anywhere conflicted on that
    one line in GitHub's merge (4 of the 8 conflicted catch-ups over #180-#192
    had no other conflict); each reader takes ``len(probes)`` instead."""

    @staticmethod
    def _verb(tree, verb: str) -> list[str]:
        root = tree["ledger"].parents[1]
        (root / "site").write_text("", encoding="utf-8")  # the fixture probes' subject
        if verb == "strike":
            _closed(tree, "DEF-1")
        return {
            "strike": ["strike", "DEF-1", "--text-file", str(tree["closing"])],
            "file": ["file", "DEF-3", "--section", "C1", "--after", "DEF-2", "--anchor", "a",
                     "--text-file", str(tree["body"]), "--severity", "nit", "--subject", "a",
                     "--why-not", "no local oracle"],
            "repin": ["repin", "DEF-1", "--reason", "value unchanged"],
        }[verb]

    @pytest.mark.parametrize("verb", ["strike", "file", "repin"])
    def test_a_stale_count_loads_and_every_writer_drops_the_key(self, lr, tree, verb):
        """A roster that still carries a ``_count`` (any value: there is
        nothing to compare it with) is read, and the write removes the key.
        Dies to: a writer that re-derives and writes the key again."""
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        data["_count"] = 99
        tree["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        root = str(tree["ledger"].parents[1])
        assert lr.main(_args(tree, "--root", root, *self._verb(tree, verb))) == 0
        assert "_count" not in json.loads(tree["probes"].read_text(encoding="utf-8"))

    def test_a_file_beside_a_strike_of_another_row_merges_clean(self, lr, tmp_path):
        """The shape the stored total alone made conflict: one lane files a row,
        the other strikes a row two entries away. Earned red: against the
        writers that re-derived ``_count`` the merge conflicts on that line."""
        def file_(t):
            return lr.main(_args(t, "--root", str(t["ledger"].parents[1]), "file", "DEF-3", "--section",
                                 "C1", "--after", "DEF-2", "--anchor", "a", "--text-file", str(t["body"]),
                                 "--severity", "nit", "--subject", "a", "--why-not", "no local oracle"))

        def strike_(t):
            return lr.main(_args(t, "--root", str(t["ledger"].parents[1]), "strike", "DEF-1",
                                 "--text-file", str(t["closing"])))

        merged, _repo = _two_lanes(tmp_path, file_, strike_)
        assert merged.returncode == 0, f"conflicted: {merged.stdout}"

    def test_two_filings_still_conflict_and_never_on_a_count(self, lr, tmp_path):
        """The negative control, and the residual a derived count does not
        reach: two lanes appending at the roster's end collide on the entries
        (and on adjacent ledger rows). The merge still sees a conflict, so the
        clean merge above is not a blind oracle, and no block spans a count."""
        def file_as(rid):
            def run(t):
                return lr.main(_args(t, "--root", str(t["ledger"].parents[1]), "file", rid, "--section",
                                     "C1", "--after", "DEF-2", "--anchor", f"a/{rid}", "--text-file",
                                     str(t["body"]), "--severity", "nit", "--subject", "a",
                                     "--why-not", "no local oracle"))
            return run

        merged, repo = _two_lanes(tmp_path, file_as("DEF-3"), file_as("DEF-4"))
        assert merged.returncode == 1
        tree_oid, *paths = [ln for ln in merged.stdout.splitlines() if ln.strip()]
        assert "task-packs/LEDGER_PROBES.json" in paths
        body = subprocess.run(["git", "cat-file", "-p", f"{tree_oid}:task-packs/LEDGER_PROBES.json"],
                              cwd=repo, capture_output=True, text=True, encoding="utf-8").stdout
        blocks = [b.split("\n>>>>>>> ")[0] for b in body.split("\n<<<<<<< ")[1:]]
        assert blocks and not any('"_count"' in b for b in blocks)


class TestMissingProbesFileIsCreated:
    """A ledger nobody has filed into yet has no probes file, and every verb
    crashed on it with a ``FileNotFoundError`` (measured 2026-09-30 on an empty
    skeleton). The file is created -- but only for a ledger with no live row.
    Every row a verb files gets a roster entry, so a live row with no file
    means the roster was LOST, and starting an empty one would hide every
    entry it held."""

    _STRUCK = ("| ~~`DEF-1`~~ | site | ✅ **CLOSED 2026-09-01 — landed** PRIOR TEXT: what | major |",
               "| ~~`DEF-2`~~ | site | ✅ **CLOSED 2026-09-01 — landed** PRIOR TEXT: what | minor |")
    _STRUCK_INDEX = ("| ~~`DEF-1`~~ | §C1 | site |", "| ~~`DEF-2`~~ | §C1 | site |")

    def _why_not(self, tree, rid="DEF-3"):
        return _args(tree, "file", rid, "--section", "C1", "--after", "DEF-2",
                     "--anchor", "a", "--text-file", str(tree["body"]), "--severity", "nit",
                     "--subject", "a", "--why-not", "no local oracle")

    def test_filing_into_a_ledger_with_no_live_row_creates_the_probes_file(self, lr, tree):
        tree["ledger"].write_text(_ledger(c1_rows=self._STRUCK, appendix=self._STRUCK_INDEX),
                                  encoding="utf-8")
        tree["probes"].unlink()
        assert lr.main(self._why_not(tree)) == 0
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        assert [p["id"] for p in data["probes"]] == ["DEF-3"]
        assert "_count" not in data
        assert b"\r\n" not in tree["probes"].read_bytes()
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(tree["ledger"].read_text(encoding="utf-8")) == []

    def test_a_dry_run_creates_nothing(self, lr, tree):
        tree["ledger"].write_text(_ledger(c1_rows=self._STRUCK, appendix=self._STRUCK_INDEX),
                                  encoding="utf-8")
        tree["probes"].unlink()
        assert lr.main(_args(tree, "--dry-run", *self._why_not(tree)[6:])) == 0
        assert not tree["probes"].exists()

    def test_a_missing_file_beside_live_rows_is_refused_by_every_verb(self, lr, tree, capsys):
        tree["probes"].unlink()
        before = tree["ledger"].read_text(encoding="utf-8")
        verbs = (
            self._why_not(tree),
            _args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"])),
            _args(tree, "repin", "DEF-1", "--reason", "moved", "--severity", "nit"),
        )
        for argv in verbs:
            assert lr.main(argv) == 2, argv[6]
            err = capsys.readouterr().err
            assert "2 live row(s)" in err and "LEDGER_PROBES.json" in err, err
        assert tree["ledger"].read_text(encoding="utf-8") == before
        assert not tree["probes"].exists()


#: A ledger nobody has filed into: the counts pointer, the section-2 heading
#: and its vocabulary tables, an empty class index and an empty Appendix B --
#: no class section yet. The shape Task 0 of the adopter port drove on
#: 2026-09-30, where no verb could add the first class or its first row.
_SKELETON = """# Forward Ledger

**Counts are derived, never stored here:** run the generator with --print.

## §2 — Open fixes, by unit of work

| population | what it means |
|---|---|
| LOGIC_BUG | code behaves wrongly |
| HYGIENE | docs |
| OPERATOR_ACTION | no code fix exists |

| audience |
|---|
| **ADOPTER** — a person who uses what this repository ships |
| MAINTAINER |
| OPERATOR |

### Class index

| § | class | population | audience | effort |
|---|---|---|---|---|

## Appendix B — id index

| id | § | site |
|---|---|---|
"""
#: The same skeleton as a ledger seeded before 2026-10-09 carries it, every
#: total stored: an adopter's file the first verb run after an upgrade meets.
_SKELETON_WITH_TOTALS = """# Forward Ledger

**Live: 0** — 0 logic bugs · 0 hygiene · 0 operator actions.
**0** reach an adopter.

## §2 — Open fixes, by unit of work (0 LIVE issues in 0 classes + 0 standalone)

| population | live | what it means |
|---|---|---|
| LOGIC_BUG | 0 | code behaves wrongly |
| HYGIENE | 0 | docs |
| OPERATOR_ACTION | 0 | no code fix exists |

| audience | live |
|---|---|
| **ADOPTER** — a person who uses what this repository ships | **0** |
| MAINTAINER | 0 |
| OPERATOR | 0 |

### Class index

| § | class | members | population | audience | effort |
|---|---|---|---|---|---|

## Appendix B — id index

| id | § | site |
|---|---|---|
"""


class TestClassVerb:
    def _class(self, lr, tree, *rest):
        return lr.main(_args(tree, "class", *rest))

    def test_class_opens_an_index_row_and_an_empty_section_that_converge(self, lr, tree):
        from tests._md_anchors import heading_anchors

        assert self._class(lr, tree, "C7", "--title", "Make X do Y",
                           "--population", "HYGIENE", "--audience", "MAINTAINER") == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "### §C7 — Make X do Y" in text
        index = [ln for ln in text.splitlines() if ln.startswith("| [§C7]")]
        assert index == ["| [§C7](#c7--make-x-do-y) | Make X do Y | HYGIENE | MAINTAINER | — |"]
        assert "c7--make-x-do-y" in heading_anchors(text)
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.ledger_sections(text)["§C7"] == []
        assert gen.find_drift(text) == []

    def test_a_mixed_class_gets_the_two_tag_columns(self, lr, tree):
        assert self._class(lr, tree, "C8", "--title", "Standalone",
                           "--population", "MIXED", "--audience", "MIXED") == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        section = text.split("### §C8", 1)[1]
        assert "| id | site | what | sev | pop | aud |" in section

    @pytest.mark.parametrize("name,title,why", [
        ("C1", "Again", "already exists"),
        ("X7", "Bad name", "C<n>"),
        ("C9", "a | b", "no '|'"),
    ])
    def test_a_bad_class_is_refused_and_nothing_written(self, lr, tree, capsys, name, title, why):
        before = tree["ledger"].read_text(encoding="utf-8")
        assert self._class(lr, tree, name, "--title", title,
                           "--population", "HYGIENE", "--audience", "MAINTAINER") == 2
        assert why in capsys.readouterr().err
        assert tree["ledger"].read_text(encoding="utf-8") == before

    def test_dry_run_writes_nothing(self, lr, tree, capsys):
        before = tree["ledger"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "--dry-run", "class", "C7", "--title", "T",
                             "--population", "HYGIENE", "--audience", "MAINTAINER")) == 0
        assert "| [§C7](#c7--t) |" in capsys.readouterr().out
        assert tree["ledger"].read_text(encoding="utf-8") == before


class TestFileIntoAnEmptySection:
    def _first(self, lr, tree, section, *extra):
        return lr.main(_args(
            tree, "file", "DEF-3", "--section", section, "--anchor", "a",
            "--text-file", str(tree["body"]), "--severity", "nit", "--subject", "a",
            "--why-not", "no local oracle", *extra,
        ))

    def test_the_first_row_of_a_new_class_needs_no_after(self, lr, tree):
        assert lr.main(_args(tree, "class", "C7", "--title", "New", "--population", "HYGIENE",
                             "--audience", "MAINTAINER")) == 0
        assert self._first(lr, tree, "C7") == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.ledger_sections(text)["§C7"] == ["| `DEF-3` | a | **A new defect.** Who: an adopter. | nit |"]
        assert text.rstrip().endswith("| `DEF-3` | §C7 | a |")
        assert gen.find_drift(text) == []

    def test_a_section_with_rows_still_needs_after(self, lr, tree, capsys):
        assert self._first(lr, tree, "C1") == 2
        assert "give --after" in capsys.readouterr().err

    def test_an_unknown_section_is_refused(self, lr, tree, capsys):
        assert self._first(lr, tree, "C9") == 2
        assert "no class section §C9" in capsys.readouterr().err

    def test_an_empty_ledger_round_trips_class_file_strike(self, lr, tmp_path, monkeypatch):
        """class -> first row (probe driven) -> strike, with the generator's own
        ``--check`` green after each verb and the probe file born on the first
        filing -- the whole lifecycle an adopter's first defect class needs."""
        packs = tmp_path / "task-packs"
        packs.mkdir()
        ledger, probes = packs / "FORWARD_LEDGER.md", packs / "LEDGER_PROBES.json"
        ledger.write_text(_SKELETON, encoding="utf-8")
        (tmp_path / "body.md").write_text("**First.** Who: the maintainer.", encoding="utf-8")
        (tmp_path / "close.md").write_text("fixed", encoding="utf-8")
        (tmp_path / "state.txt").write_text("open", encoding="utf-8")
        base = ["--root", str(tmp_path), "--ledger", str(ledger), "--probes", str(probes),
                "--date", "2026-09-30"]
        gen = lr._load("generate_ledger_regions")
        monkeypatch.setattr(gen, "_LEDGER", ledger)
        monkeypatch.setattr(gen, "_PROBES", probes)

        assert lr.main([*base, "class", "C1", "--title", "Initialise",
                        "--population", "OPERATOR_ACTION", "--audience", "MAINTAINER"]) == 0
        assert gen.main(["--check"]) == 0
        assert lr.main([*base, "file", "ONB-1", "--section", "C1", "--anchor", "cc/GOAL.md",
                        "--text-file", str(tmp_path / "body.md"), "--severity", "minor",
                        "--subject", "body.md", "--probe-cmd", "python -c \"print(open('state.txt').read().strip())\"",
                        "--open-value", "open"]) == 0
        assert gen.main(["--check"]) == 0
        assert _derived(lr, ledger.read_text(encoding="utf-8")) == (1, 1, [])
        assert [p["id"] for p in json.loads(probes.read_text(encoding="utf-8"))["probes"]] == ["ONB-1"]
        # the lane fixed it: the probe stops printing its open value, which the strike's head drive reads
        (tmp_path / "state.txt").write_text("closed", encoding="utf-8")
        assert lr.main([*base, "strike", "ONB-1", "--text-file", str(tmp_path / "close.md")]) == 0
        assert gen.main(["--check"]) == 0
        text = ledger.read_text(encoding="utf-8")
        assert _derived(lr, text) == (0, 1, []) and "| ~~`ONB-1`~~ | §C1 | cc/GOAL.md |" in text
        assert json.loads(probes.read_text(encoding="utf-8"))["probes"] == []

    def test_the_first_verb_on_a_ledger_that_stores_totals_strips_them(self, lr, tmp_path):
        """An adopter's ledger seeded before the totals left: the class verb
        converges the whole file, so it comes out as a ledger seeded after --
        no total left for two lanes to rewrite -- with the new class in it."""
        out = {}
        for name, seed in (("new", _SKELETON), ("old", _SKELETON_WITH_TOTALS)):
            packs = tmp_path / name / "task-packs"
            packs.mkdir(parents=True)
            ledger = packs / "FORWARD_LEDGER.md"
            ledger.write_text(seed, encoding="utf-8", newline="\n")
            assert lr.main(["--root", str(tmp_path / name), "--ledger", str(ledger),
                            "--probes", str(packs / "LEDGER_PROBES.json"), "--date", "2026-10-09",
                            "class", "C1", "--title", "Initialise",
                            "--population", "HYGIENE", "--audience", "MAINTAINER"]) == 0
            out[name] = ledger.read_text(encoding="utf-8")
        old, new = out["old"].splitlines(), out["new"].splitlines()
        assert _derived(lr, out["old"])[2] == []
        assert old[2] == lr._load("generate_ledger_regions").COUNTS_POINTER  # the headline's place
        assert old[3:] == new[3:]


class TestTheVerbsTakeALock:
    """Two writing verbs at once lost a row and tore the ledger/roster pair
    (driven 2026-09-30 in the failure-mode review: shared fixed temp names,
    the ledger written before the roster). Every writing verb now holds an
    O_EXCL lock beside the ledger; a second one refuses and writes nothing."""

    def test_a_held_lock_refuses_every_writing_verb_and_writes_nothing(self, lr, tree, capsys):
        lock = tree["ledger"].with_name(tree["ledger"].name + ".lock")
        lock.write_text("pid 4242\n", encoding="utf-8")
        before = tree["ledger"].read_bytes(), tree["probes"].read_bytes()
        verbs = (
            _args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"])),
            _args(tree, "class", "C7", "--title", "T", "--population", "HYGIENE",
                  "--audience", "MAINTAINER"),
            _args(tree, "file", "DEF-3", "--section", "C1", "--after", "DEF-2", "--anchor", "a",
                  "--text-file", str(tree["body"]), "--severity", "nit", "--subject", "a",
                  "--why-not", "x"),
        )
        for argv in verbs:
            assert lr.main(argv) == 2, argv[6]
            err = capsys.readouterr().err
            assert "pid 4242" in err and "one at a time" in err, err
        assert (tree["ledger"].read_bytes(), tree["probes"].read_bytes()) == before
        assert lock.read_text(encoding="utf-8") == "pid 4242\n", "a refused verb removed the holder's lock"

    def test_a_verb_with_no_ledger_says_so_and_takes_no_lock(self, lr, tmp_path, capsys):
        """Deleting the ledger is how a repository stops keeping one; the lock's
        O_CREAT beside a missing task-packs/ raised FileNotFoundError before a
        word was said (both reviewers, 2026-09-30)."""
        body = tmp_path / "body.md"
        body.write_text("x", encoding="utf-8")
        rc = lr.main(["--root", str(tmp_path), "class", "C1", "--title", "T",
                      "--population", "HYGIENE", "--audience", "MAINTAINER"])
        assert rc == 2
        assert "no ledger at" in capsys.readouterr().err
        assert not (tmp_path / "task-packs").exists()

    def test_the_lock_is_released_after_a_verb_and_a_dry_run_takes_none(self, lr, tree):
        lock = tree["ledger"].with_name(tree["ledger"].name + ".lock")
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        assert not lock.exists()
        lock.write_text("pid 1\n", encoding="utf-8")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-2",
                             "--text-file", str(tree["closing"]))) == 0


class TestAPreviewSurvivesACp1252Console:
    def test_a_dry_run_strike_prints_on_a_cp1252_stream(self, tree):
        """A struck row carries the closed-row tick; printing it to a cp1252
        stdout raised UnicodeEncodeError (driven 2026-09-30, the Bash tool's
        pipe on Windows). Driven as the CLI under that stdout, which is the
        failure; the verb now replaces what the stream cannot show."""
        import os
        import subprocess
        env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
        proc = subprocess.run(
            [sys.executable, str(MODULE_PATH), *_args(tree, "--dry-run", "strike", "DEF-1",
                                                      "--text-file", str(tree["closing"]))],
            capture_output=True, env=env, timeout=45,
        )
        assert proc.returncode == 0, proc.stderr.decode("cp1252", "replace")
        assert b"CLOSED 2026-09-06" in proc.stdout


class TestTheVerbsShareOneRoot:
    """The probe's working directory, the ledger and the roster come from one
    root, found by walking up from where the verb runs. Before, ``--ledger``
    and ``--probes`` defaulted from the script's own checkout while the probe
    ran in ``--root``, so the two could name different trees.

    The ids are ``ZZZ-`` on purpose: run against a checkout whose defaults
    still point at its own live ledger, ``--after ZZZ-2`` finds no row there
    and the verb refuses before it writes anything."""

    def test_a_verb_run_from_a_subdirectory_files_into_that_trees_ledger(
        self, lr, tree, monkeypatch
    ):
        root = tree["ledger"].parents[1]
        tree["ledger"].write_text(_ledger(
            c1_rows=("| `ZZZ-1` | site | what | major |", "| `ZZZ-2` | site | what | minor |"),
            appendix=("| `ZZZ-1` | §C1 | site |", "| `ZZZ-2` | §C1 | site |"),
        ), encoding="utf-8")
        tree["probes"].write_text(json.dumps({"_count": 0, "probes": []}) + "\n", encoding="utf-8")
        (root / "marker.txt").write_text("open=True\n", encoding="utf-8")
        deep = root / "a" / "b"
        deep.mkdir(parents=True)
        monkeypatch.chdir(deep)
        rc = lr.main([
            "--date", "2026-09-06", "file", "ZZZ-3", "--section", "C1", "--after", "ZZZ-2",
            "--anchor", "a", "--text-file", str(tree["body"]), "--severity", "minor",
            "--probe-cmd", "python -c \"print(open('marker.txt').read().strip())\"",
            "--open-value", "open=True", "--subject", "body.md", "--inputs", "marker.txt",
        ])
        assert rc == 0
        assert "| `ZZZ-3` | a |" in tree["ledger"].read_text(encoding="utf-8")
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        assert [p["id"] for p in data["probes"]] == ["ZZZ-3"]
        assert data["probes"][0]["inputs"] == ["marker.txt"]


class TestATwoIdRow:
    """DEF-863. A member row's id cell may carry two ids (`DEF-536` `LG-1`:
    eight live rows on 2026-09-20, three ids in `DEF-371a`'s). Every verb keyed
    the row on a lone id before the pipe, so such a row was invisible to strike,
    repin and file --after by EITHER id, and seven of the eight carried probes
    nothing could ever stamp. The cell is one row: addressed by any of its ids,
    struck as a whole, indexed once per id, its probes retired together.

    Earn-the-red (driven against the pre-change module): every leg reds on
    "no unstruck member row" / "no member row for --after" today."""

    _ROW = "| `DEF-1` `LG-9` | site | what | major |"

    def _two_id_tree(self, tree):
        tree["ledger"].write_text(_ledger(
            c1_rows=(self._ROW, "| `DEF-2` | site | what | minor |"),
            appendix=("| `DEF-1` | §C1 | site |", "| `LG-9` | §C1 | site |",
                      "| `DEF-2` | §C1 | site |"),
        ), encoding="utf-8")
        # the roster is written fresh (not appended), so a test may rebuild the
        # tree mid-way
        data = {"probes": [
            {"id": "DEF-1", "subject": "site", "cmd": "echo a", "open_value": "a", "why_not": None, "row_sha": "x"},
            {"id": "DEF-2", "subject": "site", "cmd": "echo b", "open_value": "b", "why_not": None, "row_sha": "y"},
            {"id": "LG-9", "subject": "site", "cmd": "echo z", "open_value": "z", "why_not": None, "row_sha": "w"},
        ]}
        tree["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        (tree["ledger"].parents[1] / "site").write_text("", encoding="utf-8")
        return ["--root", str(tree["ledger"].parents[1])]

    @pytest.mark.parametrize("rid", ["DEF-1", "LG-9"])
    def test_a_strike_by_either_id_closes_the_whole_cell_and_retires_every_probe_it_owns(
        self, lr, tree, capsys, rid
    ):
        self._two_id_tree(tree)
        _closed(tree, "DEF-1", "LG-9")
        assert lr.main(_args(tree, "strike", rid, "--text-file", str(tree["closing"]))) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert ("| ~~`DEF-1`~~ ~~`LG-9`~~ | site | ✅ **CLOSED 2026-09-06 — landed in abc123 after "
                "one pass of each red team** PRIOR TEXT: what | major |") in text
        assert "| ~~`DEF-1`~~ | §C1 | site |" in text and "| ~~`LG-9`~~ | §C1 | site |" in text
        assert _derived(lr, text)[0] == 1
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        assert [p["id"] for p in data["probes"]] == ["DEF-2"] and "_count" not in data
        assert "2 probe(s) retired" in capsys.readouterr().out
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(text) == []
        # the closed cell is closed by either id
        assert lr.main(_args(tree, "strike", "LG-9", "--text-file", str(tree["closing"]))) == 2
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2

    def test_a_repin_by_the_co_id_keeps_the_cell_whole_stamps_its_own_probe_and_names_the_sibling(
        self, lr, tree, capsys
    ):
        root = self._two_id_tree(tree)
        assert lr.main(_args(tree, *root, "repin", "LG-9", "--anchor", "site2",
                             "--reason", "the site moved")) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        line = "| `DEF-1` `LG-9` | site2 | what | major |"
        assert line in text
        # every id of the cell has an index row, and the anchor moves on each
        assert "| `DEF-1` | §C1 | site2 |" in text and "| `LG-9` | §C1 | site2 |" in text
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        by_id = {p["id"]: p for p in data["probes"]}
        chk = lr._load("check_ledger_probes")
        assert by_id["LG-9"]["row_sha"] == chk.row_sha(line)
        assert by_id["LG-9"]["text_sha"] == chk.text_sha(line)
        assert by_id["LG-9"]["verified_2026_09_06"].startswith(
            "STILL_OPEN (re-pinned value unchanged on 2026-09-06: the site moved")
        # the sibling's probe was not driven, so nothing about it moved -- and
        # the verb names it, so the operator knows one verb re-witnessed one id
        assert by_id["DEF-1"] == {"id": "DEF-1", "subject": "site", "cmd": "echo a",
                                  "open_value": "a", "why_not": None, "row_sha": "x"}
        assert "DEF-1" in capsys.readouterr().out
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(text) == []

    def test_a_filing_after_the_co_id_lands_after_the_shared_row_and_a_duplicate_co_id_is_refused(
        self, lr, tree, capsys
    ):
        root = self._two_id_tree(tree)
        common = [*root, "file", "DEF-3", "--section", "C1", "--after", "LG-9",
                  "--anchor", "new/site.py::fn", "--text-file", str(tree["body"]),
                  "--severity", "minor", "--probe-cmd", "echo open=True",
                  "--open-value", "open=True", "--subject", "body.md"]
        assert lr.main(_args(tree, *common)) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        member = "| `DEF-3` | new/site.py::fn | **A new defect.** Who: an adopter. | minor |"
        assert text.index(self._ROW) < text.index(member) < text.index("| `DEF-2` | site")
        assert (text.index("| `LG-9` | §C1 | site |")
                < text.index("| `DEF-3` | §C1 | new/site.py::fn |")
                < text.index("| `DEF-2` | §C1 | site |"))
        assert _derived(lr, text)[0] == 3
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(text) == []
        # a co-id already has a member row: filing it again is the duplicate refusal
        before = tree["ledger"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, *root, "file", "LG-9", "--section", "C1", "--after", "DEF-2",
                             "--anchor", "a", "--text-file", str(tree["body"]),
                             "--severity", "nit", "--probe-cmd", "echo open=True",
                             "--open-value", "open=True", "--subject", "body.md")) == 2
        assert "already has a member row" in capsys.readouterr().err
        assert tree["ledger"].read_text(encoding="utf-8") == before

    def test_the_section_holding_a_row_is_read_by_either_id(self, lr, tree):
        self._two_id_tree(tree)
        text = tree["ledger"].read_text(encoding="utf-8")
        assert lr._section_holding(text, "LG-9") == "§C1" == lr._section_holding(text, "DEF-1")

    def test_a_dry_run_names_every_index_row_and_puts_the_sibling_note_on_its_own_line(
        self, lr, tree, capsys
    ):
        """Both reviews: the dry run is the one look an operator gets before the
        verb writes both files. A strike's dry run names each id's index row
        by state (the single-id wording had regressed to "not found" for an
        already-struck index row); a repin's sibling note used to be glued to
        the closing brace of a 700-character JSON dump."""
        root = self._two_id_tree(tree)
        _closed(tree, "DEF-1", "LG-9")
        # one index row already struck by hand: the note says so, per id
        text = tree["ledger"].read_text(encoding="utf-8")
        tree["ledger"].write_text(text.replace("| `LG-9` | §C1 | site |", "| ~~`LG-9`~~ | §C1 | site |"),
                                  encoding="utf-8")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        out = capsys.readouterr().out
        assert "(index rows: DEF-1 struck, LG-9 already struck; 2 probe(s) would retire)" in out
        # single-id path: the three states are told apart
        tree["ledger"].write_text(_ledger(appendix=("| ~~`DEF-1`~~ | §C1 | site |", "| `DEF-2` | §C1 | site |")),
                                  encoding="utf-8")
        assert lr.main(_args(tree, "--reconcile-count", "--dry-run", "strike", "DEF-1",
                             "--text-file", str(tree["closing"]))) == 0
        assert "(index row already struck; 1 probe(s) would retire)" in capsys.readouterr().out
        # repin dry run: row, then the note on its own line, then parseable JSON
        self._two_id_tree(tree)
        assert lr.main(_args(tree, *root, "--dry-run", "repin", "LG-9", "--reason", "r")) == 0
        lines = capsys.readouterr().out.rstrip("\n").split("\n")
        assert lines[0] == self._ROW
        assert lines[1].startswith("(shares its row with DEF-1")
        assert json.loads("\n".join(lines[2:]))["id"] == "LG-9"

    def test_a_half_struck_cell_is_refused_by_every_verb(self, lr, tree, capsys):
        """Strike state is read at row level and a strike rewrites the whole
        cell, so a cell struck on some ids only would close a live co-id as
        collateral or re-pin a closed one. No such row exists (0 on
        2026-09-20); the verbs refuse it rather than guess (code review)."""
        root = self._two_id_tree(tree)
        text = tree["ledger"].read_text(encoding="utf-8")
        tree["ledger"].write_text(text.replace(self._ROW, "| `DEF-1` ~~`LG-9`~~ | site | what | major |"),
                                  encoding="utf-8")
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "strike", "LG-9", "--text-file", str(tree["closing"]))) == 2
        assert "struck on some ids and not others" in capsys.readouterr().err
        assert lr.main(_args(tree, *root, "repin", "DEF-1", "--reason", "r")) == 2
        assert "struck on some ids and not others" in capsys.readouterr().err
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before


class TestTheMixedClassShape:
    """§C0's rows carry `| sev | pop | aud |`; every verb must round-trip them."""

    def _mixed_tree(self, tree):
        tree["ledger"].write_text(_ledger(
            mixed=True,
        ), encoding="utf-8")
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        data["probes"].append({"id": "DEF-3", "subject": "site", "cmd": "echo c", "open_value": "c",
                               "why_not": None, "row_sha": "z"})
        tree["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")

    def test_a_strike_keeps_the_two_tag_cells(self, lr, tree):
        self._mixed_tree(tree)
        assert lr.main(_args(tree, "strike", "DEF-3", "--text-file", str(tree["closing"]))) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "PRIOR TEXT: what | nit | HYGIENE | MAINTAINER |" in text
        assert _tally(lr, text)["HYGIENE"] == 0 and _tally(lr, text)["MAINTAINER"] == 0
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(text) == []

    def test_a_five_cell_row_is_refused(self, lr):
        with pytest.raises(lr.RowShape, match="not 4 .* or 6"):
            lr._cells("| `DEF-9` | site | what | nit | HYGIENE |")

    def test_a_tag_outside_the_vocabulary_is_refused(self, lr):
        with pytest.raises(lr.RowShape, match="not a population"):
            lr._cells("| `DEF-9` | site | what | nit | HYGIENE | ADOPTERS |")

    def test_filing_into_a_mixed_section_needs_both_tags_and_lands_them(self, lr, tree):
        self._mixed_tree(tree)
        common = ["--root", str(tree["ledger"].parents[1]), "file", "DEF-4", "--section", "C2",
                  "--after", "DEF-3", "--anchor", "new/site.py", "--text-file", str(tree["body"]),
                  "--severity", "minor", "--probe-cmd", "echo open=True", "--open-value", "open=True",
                  "--subject", "body.md"]
        # without the tags the verb refuses before anything is written
        before = tree["ledger"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, *common)) == 2
        assert tree["ledger"].read_text(encoding="utf-8") == before
        assert lr.main(_args(tree, *common, "--population", "LOGIC_BUG", "--audience", "ADOPTER")) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "| `DEF-4` | new/site.py | **A new defect.** Who: an adopter. | minor | LOGIC_BUG | ADOPTER |" in text
        assert _tally(lr, text)["LOGIC_BUG"] == 3 and _tally(lr, text)["ADOPTER"] == 3

    def test_filing_tags_into_a_classed_section_is_refused(self, lr, tree, capsys):
        """A row under a token-tagged class is counted by the class; cells on it
        would be printed and never counted (both reviewers drove this)."""
        before = tree["ledger"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]), "file", "DEF-3",
                             "--section", "C1", "--after", "DEF-2", "--anchor", "a",
                             "--text-file", str(tree["body"]), "--severity", "nit",
                             "--probe-cmd", "echo open=True", "--open-value", "open=True",
                             "--subject", "body.md", "--population", "HYGIENE",
                             "--audience", "MAINTAINER")) == 2
        assert "inherits its tags from the class index" in capsys.readouterr().err
        assert tree["ledger"].read_text(encoding="utf-8") == before

    def _one_axis_mixed_tree(self, tree, *, first_row="| `DEF-1` | site | what | major | LOGIC_BUG | ADOPTER |"):
        """§C1 declared LOGIC_BUG / MIXED -- the shape the live ledger already
        carries for four classes (§C13, §C14, §C18, §C20 on 2026-09-20) and the
        third rebuild's file for ten, its §C1 being OPERATOR_ACTION / MIXED. The
        generator counts such a class by the class tag on the classed axis and
        by each row's OWN cell on the MIXED axis, so every row there is the
        6-cell shape and the classed cell must repeat the class tag. Callers
        that need a stranded row pass a 4-cell ``first_row``."""
        tree["ledger"].write_text(_ledger(
            c1_tags=("LOGIC_BUG", "MIXED"),
            c1_rows=(first_row,
                     "| `DEF-2` | site | what | minor | LOGIC_BUG | MAINTAINER |"),
        ), encoding="utf-8")

    def test_filing_into_a_section_mixed_on_one_axis_needs_both_tags_and_the_classed_one_must_match(
        self, lr, tree, capsys
    ):
        """Until 2026-09-20 the verb keyed "MIXED" on BOTH axes (`DEF-776`), so a
        row filed into a one-axis-MIXED class went out as the 4-cell shape and
        was refused only by convergence, with the generator's dump -- or, with
        tags, was refused as "inherits its tags from the class index", which is
        false for the MIXED axis. Earn-the-red (driven against the pre-change
        module by both reviewers): leg 1 reds because the old refusal is the
        convergence dump, not the verb's own MIXED-on-one-axis wording; leg 2
        reds on "inherits its tags"; leg 3 reds because the filing is refused
        instead of landing."""
        self._one_axis_mixed_tree(tree)
        common = ["--root", str(tree["ledger"].parents[1]), "file", "DEF-3", "--section", "C1",
                  "--after", "DEF-2", "--anchor", "new/site.py", "--text-file", str(tree["body"]),
                  "--severity", "minor", "--probe-cmd", "echo open=True", "--open-value", "open=True",
                  "--subject", "body.md"]
        before = tree["ledger"].read_text(encoding="utf-8")
        # no tags: refused before anything is written, by the verb's own wording,
        # which names the token the classed axis requires
        assert lr.main(_args(tree, *common)) == 2
        err = capsys.readouterr().err
        assert "is MIXED on one axis (LOGIC_BUG / MIXED)" in err and "--population LOGIC_BUG" in err
        assert tree["ledger"].read_text(encoding="utf-8") == before
        # tags, but the classed axis disagrees with the class index: refused by name
        assert lr.main(_args(tree, *common, "--population", "HYGIENE", "--audience", "OPERATOR")) == 2
        err = capsys.readouterr().err
        assert "declares population 'LOGIC_BUG'" in err and "HYGIENE" in err
        assert tree["ledger"].read_text(encoding="utf-8") == before
        # the classed axis repeats the class tag, the MIXED axis is the row's own: lands 6-cell
        assert lr.main(_args(tree, *common, "--population", "LOGIC_BUG", "--audience", "OPERATOR")) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "| `DEF-3` | new/site.py | **A new defect.** Who: an adopter. | minor | LOGIC_BUG | OPERATOR |" in text
        assert _tally(lr, text)["OPERATOR"] == 1 and _tally(lr, text)["LOGIC_BUG"] == 3
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(text) == []

    def test_filing_refuses_a_section_that_is_not_the_one_after_sits_in(self, lr, tree, capsys):
        """`--section` selects the class whose tags the new row is validated
        against, but the row lands after `--after`'s row wherever that is: with
        `--section C2 --after DEF-1` the row was validated against §C2, inserted
        into §C1, indexed under §C2, and converged because the two classes
        happened to agree (both reviewers drove it, 2026-09-20). Earn-the-red:
        drop the `_section_holding` check in `file_row` and the call lands."""
        self._mixed_tree(tree)
        before = tree["ledger"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]), "file", "DEF-4",
                             "--section", "C2", "--after", "DEF-1", "--anchor", "a",
                             "--text-file", str(tree["body"]), "--severity", "nit",
                             "--probe-cmd", "echo open=True", "--open-value", "open=True",
                             "--subject", "body.md", "--population", "LOGIC_BUG",
                             "--audience", "ADOPTER")) == 2
        err = capsys.readouterr().err
        assert "--after DEF-1 sits in §C1, not §C2" in err
        assert tree["ledger"].read_text(encoding="utf-8") == before

    def test_repin_cannot_retag_the_classed_axis_of_a_one_axis_mixed_row(self, lr, tree, capsys):
        """`repin --population` on a row whose class index declares the population
        token would print the row's cell while the class keeps counting its own
        (the generator's contradiction arm); the MIXED axis stays retaggable.
        Earn-the-red: drop the classed-axis check in `repin` and the first call
        is refused only by convergence -- after the probe run and the sidecar
        write, as the generator's dump rather than a refusal the verb owns."""
        self._one_axis_mixed_tree(tree)
        (tree["ledger"].parents[1] / "site").write_text("", encoding="utf-8")
        root = ["--root", str(tree["ledger"].parents[1])]
        before = tree["ledger"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, *root, "repin", "DEF-1", "--population", "HYGIENE", "--reason", "r")) == 2
        assert "sits in §C1, which declares population 'LOGIC_BUG'" in capsys.readouterr().err
        assert tree["ledger"].read_text(encoding="utf-8") == before
        assert lr.main(_args(tree, *root, "repin", "DEF-1", "--audience", "OPERATOR",
                             "--reason", "its named user is the operator")) == 0
        assert "| `DEF-1` | site | what | major | LOGIC_BUG | OPERATOR |" in tree["ledger"].read_text(encoding="utf-8")

    def test_repin_widens_a_row_stranded_4_cell_when_its_class_went_mixed(self, lr, tree, capsys):
        """A rebuild flips a class to MIXED on an axis; a row it leaves 4-cell
        strands EVERY verb on the ledger, because convergence is global, and the
        old refusal ("inherits its tags from the class index") pointed the wrong
        way -- the class already IS MIXED (failure-mode pass, 2026-09-20). With
        one flag the verb names the remedy; with both it widens the row in place.
        Earn-the-red: restore the unconditional `len(cells) != 6` refusal and
        the second call is refused."""
        self._one_axis_mixed_tree(tree, first_row="| `DEF-1` | site | what | major |")
        (tree["ledger"].parents[1] / "site").write_text("", encoding="utf-8")
        root = ["--root", str(tree["ledger"].parents[1])]
        before = tree["ledger"].read_text(encoding="utf-8")
        # the stranded state is real: the generator names the row
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert any("DEF-1" in d["detail"] and "MIXED" in d["detail"] for d in gen.find_drift(before))
        # one flag: the true remedy, nothing written
        assert lr.main(_args(tree, *root, "repin", "DEF-1", "--audience", "ADOPTER", "--reason", "r")) == 2
        err = capsys.readouterr().err
        assert "still carries no tag cells" in err and "give --population and --audience together" in err
        assert tree["ledger"].read_text(encoding="utf-8") == before
        # both flags: widened, converged
        assert lr.main(_args(tree, *root, "repin", "DEF-1", "--population", "LOGIC_BUG",
                             "--audience", "ADOPTER", "--reason", "widened after §C1 went MIXED")) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "| `DEF-1` | site | what | major | LOGIC_BUG | ADOPTER |" in text
        assert gen.find_drift(text) == []

    def test_repin_retags_a_mixed_row_without_staling_its_claim(self, lr, tree):
        self._mixed_tree(tree)
        (tree["ledger"].parents[1] / "site").write_text("", encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]), "repin", "DEF-3",
                             "--audience", "ADOPTER", "--reason", "its named user is an adopter")) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        line = "| `DEF-3` | site | what | nit | HYGIENE | ADOPTER |"
        assert line in text and _tally(lr, text)["ADOPTER"] == 3
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        p = [x for x in data["probes"] if x["id"] == "DEF-3"][0]
        chk = lr._load("check_ledger_probes")
        assert p["row_sha"] == chk.row_sha(line) and p["text_sha"] == chk.text_sha(line)
        assert p["verified_2026_09_06"] == (
            "STILL_OPEN (re-pinned value unchanged on 2026-09-06: its named user is an adopter) [changed: classes]"
        )
        assert chk.text_sha(line) == chk.text_sha("| `DEF-3` | site | what | nit | HYGIENE | MAINTAINER |")

    def test_a_repin_regrades_severity_and_leaves_the_two_tag_cells_alone(self, lr, tree):
        """The 6-cell shape carries severity in the same cell as the 4-cell
        one, so the --severity leg must round-trip it without disturbing the
        tags beside it. Earn-the-red: widen `cells[3] = severity` to also
        touch cells[4] or [5] and this reds on the tag cells."""
        self._mixed_tree(tree)
        (tree["ledger"].parents[1] / "site").write_text("", encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]), "repin", "DEF-3",
                             "--severity", "major",
                             "--reason", "re-graded on realised consequence")) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "| `DEF-3` | site | what | major | HYGIENE | MAINTAINER |" in text

    def test_repin_cannot_retag_a_classed_row(self, lr, tree, capsys):
        (tree["ledger"].parents[1] / "site").write_text("", encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]), "repin", "DEF-1",
                             "--audience", "ADOPTER", "--reason", "r")) == 2
        assert "inherits its tags from the class index" in capsys.readouterr().err

    def test_one_tag_without_the_other_is_a_usage_error(self, lr, tree):
        with pytest.raises(SystemExit):
            lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]), "file", "DEF-4",
                          "--section", "C1", "--after", "DEF-2", "--anchor", "a",
                          "--text-file", str(tree["body"]), "--severity", "nit",
                          "--why-not", "x", "--subject", "body.md", "--population", "HYGIENE"))


class TestRepin:
    def _repin(self, lr, tree, *extra):
        # the fixture probe's subject is `site`; the runner refuses a subject that moved
        (tree["ledger"].parents[1] / "site").write_text("", encoding="utf-8")
        return lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]), "repin", "DEF-1", *extra))

    def _probe(self, tree):
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        return data, [p for p in data["probes"] if p["id"] == "DEF-1"][0]

    def test_repin_declares_the_inputs_the_command_reads_and_drives_them_first(self, lr, tree, capsys):
        """`DEF-858`: the verb writes the declaration and drives the probe through
        the runner's own gate with it, so a declared path absent on this tree
        refuses the re-pin (the UNRESOLVED the recurring check would report) and
        writes nothing; a later re-pin without the flag keeps the list AND still
        drives it."""
        root = tree["ledger"].parents[1]
        (root / "site").write_text("", encoding="utf-8")
        before = tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(root), "repin", "DEF-1", "--inputs",
                             "records/Done", "--reason", "the command reads the folder")) == 2
        assert "input missing: records/Done" in capsys.readouterr().err
        assert tree["probes"].read_text(encoding="utf-8") == before
        (root / "records" / "Done").mkdir(parents=True)
        (root / "records" / "Done" / "TP-1-x.md").write_text("", encoding="utf-8")  # a bare dir is "input empty"
        assert lr.main(_args(tree, "--root", str(root), "repin", "DEF-1", "--inputs",
                             "records/Done", "--inputs", "site",
                             "--reason", "the command reads the folder")) == 0
        _data, p = self._probe(tree)
        assert p["inputs"] == ["records/Done", "site"] and p["open_value"] == "a"
        assert "inputs None -> ['records/Done', 'site']" in p["verified_2026_09_06"]
        # kept, and driven: with the folder gone the kept declaration refuses
        assert self._repin(lr, tree, "--reason", "value unchanged") == 0
        assert self._probe(tree)[1]["inputs"] == ["records/Done", "site"]
        (root / "records" / "Done" / "TP-1-x.md").unlink()
        (root / "records" / "Done").rmdir()
        assert self._repin(lr, tree, "--reason", "value unchanged") == 2
        assert "input missing: records/Done" in capsys.readouterr().err

    def test_repin_inputs_is_refused_on_a_row_with_no_probe_command(self, lr, tree, capsys):
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        data["probes"][0]["cmd"] = None
        tree["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        root = tree["ledger"].parents[1]
        before = tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(root), "repin", "DEF-1", "--inputs", "site",
                             "--reason", "r")) == 2
        assert "--inputs cannot be driven" in capsys.readouterr().err
        assert tree["probes"].read_text(encoding="utf-8") == before

    def test_repin_re_points_the_subject_and_drives_the_probe_against_it(self, lr, tree, capsys):
        """A probe filed against the wrong subject -- 2026-09-21, DEF-914's read the
        packs but named the reader module it imports, and the paperwork ratchet
        (tests/test_check_ledger_probes.py) caught the shape -- had no verb to move
        it, and a hand edit of the probes file is the trace-destroying path. The
        new subject is driven first: a missing one is UNRESOLVED and re-pins nothing."""
        root = tree["ledger"].parents[1]
        (root / "site").write_text("", encoding="utf-8")
        before = tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(root), "repin", "DEF-1", "--subject",
                             "task-packs/other.md", "--reason", "the fix edits the packs")) == 2
        assert "subject missing" in capsys.readouterr().err
        assert tree["probes"].read_text(encoding="utf-8") == before
        (root / "task-packs" / "other.md").write_text("", encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(root), "repin", "DEF-1", "--subject",
                             "task-packs/other.md", "--reason", "the fix edits the packs")) == 0
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        p = next(e for e in data["probes"] if e["id"] == "DEF-1")
        assert p["subject"] == "task-packs/other.md" and p["open_value"] == "a"
        assert "subject 'site' -> 'task-packs/other.md'" in p["verified_2026_09_06"]

    def test_repin_subject_is_refused_on_a_row_with_no_probe_command(self, lr, tree, capsys):
        # Nine roster rows carry `cmd: null`; a subject written there is un-driven.
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        data["probes"][0]["cmd"] = None
        tree["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        root = tree["ledger"].parents[1]
        (root / "task-packs" / "other.md").write_text("", encoding="utf-8")
        before = tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(root), "repin", "DEF-1", "--subject",
                             "task-packs/other.md", "--reason", "r")) == 2
        assert "give --probe-cmd" in capsys.readouterr().err
        assert tree["probes"].read_text(encoding="utf-8") == before

    def test_repin_drives_the_probe_moves_the_pin_and_stamps_the_reason(self, lr, tree):
        assert self._repin(lr, tree, "--probe-cmd", "echo drifted", "--open-value", "drifted",
                           "--reason", "count moved 1 -> 2") == 0
        data, p = self._probe(tree)
        assert p["open_value"] == "drifted" and p["cmd"] == "echo drifted"
        assert p["verified_2026_09_06"] == (
            "STILL_OPEN (re-pinned 'a' -> 'drifted' on 2026-09-06: count moved 1 -> 2) [changed: probe, open value]"
        )
        text = tree["ledger"].read_text(encoding="utf-8")
        line = "| `DEF-1` | site | what | major |"
        assert line in text
        assert p["row_sha"] == hashlib.sha256(line.encode("utf-8")).hexdigest()[:12]
        assert len(data["probes"]) == 2 and "_count" not in data
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(text) == []

    def test_a_probe_that_does_not_print_the_new_value_repins_nothing(self, lr, tree, capsys):
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        # the fixture probe is `echo a`: it prints a, never drifted
        assert self._repin(lr, tree, "--open-value", "drifted", "--reason", "r") == 2
        assert "does not print the new open value 'drifted'" in capsys.readouterr().err
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before

    def test_repin_rewrites_the_text_cell_and_the_sha_the_checker_recomputes(self, lr, tree, tmp_path):
        new = tmp_path / "what.md"
        new.write_text("what, re-measured\ntoday", encoding="utf-8")
        assert self._repin(lr, tree, "--text-file", str(new), "--reason", "re-measured") == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        member = "| `DEF-1` | site | what, re-measured today | major |"
        assert member in text
        _data, p = self._probe(tree)
        assert p["row_sha"] == hashlib.sha256(member.encode("utf-8")).hexdigest()[:12]
        assert p["open_value"] == "a"  # kept: the existing probe still prints it
        # the sha the checker recomputes from the live line
        chk = lr._load("check_ledger_probes")
        assert hashlib.sha256(chk._row_line("DEF-1", text).encode("utf-8")).hexdigest()[:12] == p["row_sha"]

    def test_a_struck_row_cannot_be_repinned(self, lr, tree, capsys):
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        assert self._repin(lr, tree, "--reason", "r") == 2
        assert "no unstruck member row" in capsys.readouterr().err

    def test_repin_regrades_a_CLASSED_row_no_mixed_class_needed(self, lr, tree):
        """The severity cell is cell 4 of EVERY member row, so unlike
        --audience this needs no MIXED class -- DEF-1 is a 4-cell classed row
        and its grade moves. Before 2026-09-18 there was no verb at all and a
        re-grade was a hand edit that staled row_sha; the sha assertion below
        is what pins that it no longer does.

        Earn-the-red: drop `cells[3] = severity` in `repin` and this reds on
        the line assertion; drop the `entry.update(_pins(new_line))` that
        follows it and this reds on the sha assertion instead."""
        assert self._repin(lr, tree, "--severity", "nit",
                           "--reason", "re-graded: no adopter reaches it") == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        line = "| `DEF-1` | site | what | nit |"
        assert line in text
        assert "| `DEF-1` | site | what | major |" not in text
        _data, probe = self._probe(tree)
        chk = lr._load("check_ledger_probes")
        assert probe["row_sha"] == chk.row_sha(line), "a re-grade must not stale the claim"
        assert probe["verified_2026_09_06"] == (
            "STILL_OPEN (re-pinned value unchanged; severity major -> nit on 2026-09-06: "
            "re-graded: no adopter reaches it) [changed: severity]"
        )

    def test_repin_stamp_names_every_field_it_changed(self, lr, tree):
        """DEF-3003 (air's 914037): the stamp's `moved` clause names the value,
        the grade, the subject and the inputs but never the probe, so a
        severity re-grade and a hand-written probe stamped alike, and the
        engine's onboarding refresh could not tell an adopter's own probe from
        a re-grade. The stamp now ends with every field the repin changed: a
        re-grade names `severity` and no `probe`."""
        assert self._repin(lr, tree, "--severity", "nit", "--reason", "re-graded") == 0
        _data, probe = self._probe(tree)
        assert probe["verified_2026_09_06"].endswith(") [changed: severity]"), probe["verified_2026_09_06"]

    def test_repin_with_a_byte_equal_probe_names_no_probe(self, lr, tree):
        assert self._repin(lr, tree, "--probe-cmd", "echo a", "--open-value", "a",
                           "--reason", "re-witnessed") == 0
        _data, probe = self._probe(tree)
        assert probe["verified_2026_09_06"].endswith(") [changed: none]"), probe["verified_2026_09_06"]

    def test_repin_with_a_new_probe_names_the_probe(self, lr, tree):
        assert self._repin(lr, tree, "--probe-cmd", "python -c \"print('a')\"", "--open-value", "a",
                           "--reason", "a probe of our own") == 0
        _data, probe = self._probe(tree)
        assert probe["verified_2026_09_06"].endswith(") [changed: probe]"), probe["verified_2026_09_06"]

    def test_a_second_repin_on_one_day_carries_the_first_ones_list(self, lr, tree):
        """DEF-3003, the failure-mode re-review: a second repin on one day
        writes over that day's stamp, so a re-grade after a new probe read as
        a re-grade alone; the first one's list is carried into it."""
        assert self._repin(lr, tree, "--probe-cmd", "python -c \"print('a')\"", "--open-value", "a",
                           "--reason", "a probe of our own") == 0
        assert self._repin(lr, tree, "--severity", "nit", "--reason", "re-graded") == 0
        _data, probe = self._probe(tree)
        assert probe["verified_2026_09_06"].endswith(") [changed: probe, severity]"), probe["verified_2026_09_06"]

    def test_repin_without_severity_keeps_the_grade(self, lr, tree):
        """The false-deny twin: every other repin leg must leave cell 4 alone.
        A default that silently re-graded would be worse than no verb."""
        assert self._repin(lr, tree, "--reason", "anchor moved only",
                           "--anchor", "site2") == 0
        assert "| `DEF-1` | site2 | what | major |" in tree["ledger"].read_text(encoding="utf-8")


@pytest.mark.contract
def test_the_probes_file_is_byte_stable_under_its_own_serializer():
    """The sidecar is tracked since 2026-09-21. Pin the exact spelling
    scripts/ledger_row.py writes (`json.dumps(..., indent=1, ensure_ascii=False)`
    plus a trailing newline) so a reformat is a deliberate act, not a
    two-thousand-line hunk riding along with a one-row repin (the failure-mode
    lane, 2026-09-21)."""
    p = REPO_ROOT / "task-packs" / "LEDGER_PROBES.json"
    if not p.is_file():
        pytest.skip("no roster file: this tree folded it into task-packs/probes.d/ on 2026-10-14, "
                    "whose files the twin pin below holds to the same serializer")
    text = p.read_text(encoding="utf-8")  # ledger-read: the roster file's own bytes (the probe files' twin pin is below)
    assert json.dumps(json.loads(text), indent=1, ensure_ascii=False) + "\n" == text, (
        "task-packs/LEDGER_PROBES.json is not byte-stable under ledger_row.py's own "
        "serializer -- something reformatted it; write it through the verbs only"
    )


@pytest.mark.contract
def test_every_row_and_probe_file_is_in_the_verbs_own_spelling(lr):
    """The same pin for the ledger's rows and probes as one file each
    (``ledger_fragments``): a probe file is one entry in the roster's spelling,
    and a row file is the class line, the member row and its index lines, as
    ``ledger_row.py`` writes them. A hand-reformatted file re-pins nothing and
    rides along in the next verb's diff."""
    rows_dir, probes_dir = REPO_ROOT / "task-packs" / "ledger.d", REPO_ROOT / "task-packs" / "probes.d"
    off = []
    for p in sorted(probes_dir.glob("*.json")) if probes_dir.is_dir() else []:
        text = p.read_text(encoding="utf-8")
        if json.dumps(json.loads(text), indent=1, ensure_ascii=False) + "\n" != text:
            off.append(p.name)
    for p in sorted(rows_dir.glob("*.md")) if rows_dir.is_dir() else []:
        frag = lr._FRAG.parse_ledger_fragment(p.name, p.read_text(encoding="utf-8"))
        if isinstance(frag, str) or lr._row_file_text(frag.section, frag.member, frag.index) != p.read_text(
                encoding="utf-8"):
            off.append(p.name)
    assert not off, f"row or probe files not in the verbs' spelling (write them through the verbs only): {off}"


# ── the verbs read the mail channel's claims before they write ───────────────

def _mail_module():
    spec = importlib.util.spec_from_file_location("_mail_for_ledger_tests", REPO_ROOT / "tools" / "cc" / "mail.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _stub_channel(mail, *claims, machine="mac"):
    """A stand-in for the mail module: this box is named, the other box's
    claims are given, the fold and the overlap are the real ones."""
    import types
    return types.SimpleNamespace(
        machine_setting=lambda root, **kw: (machine, "named"),
        read_mail=lambda root, **kw: ({"win": list(claims)}, {}),
        live_claims=mail.live_claims,
        overlapping_claims=mail.overlapping_claims,
    )


class TestTheVerbsReadTheClaims:
    """Before a writing verb takes the lock, it reads the other machine's live
    claims from the local mail refs. A claim naming this ROW's id refuses by
    name (one id minted twice, or one row touched on both sides, is what the
    record merge cannot take); a claim naming only the row's CLASS is a note,
    because two rows in one class merge cleanly. Nothing is read where the
    box is unnamed or the channel is absent, and a refusal names the way past:
    --override."""

    def _file(self, lr, tree, *pre):
        return lr.main(_args(
            tree, "--root", str(tree["ledger"].parents[1]), *pre,
            "file", "DEF-3", "--section", "C1", "--after", "DEF-2",
            "--anchor", "new/site.py::fn", "--text-file", str(tree["body"]), "--severity", "minor",
            "--probe-cmd", "echo open=True", "--open-value", "open=True", "--subject", "body.md",
        ))

    def test_a_claim_on_the_id_refuses_before_anything_is_written(self, lr, tree, monkeypatch, capsys):
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", classes=["C66"], ids=["DEF-3"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs))
        before = tree["ledger"].read_text(encoding="utf-8")
        assert self._file(lr, tree) == 2
        err = capsys.readouterr().err
        assert "refused" in err and "win claims id DEF-3 on lane/c66" in err and "--override" in err
        assert tree["ledger"].read_text(encoding="utf-8") == before
        assert not tree["ledger"].with_name(tree["ledger"].name + ".lock").exists()

    def test_override_writes_and_names_the_holder(self, lr, tree, monkeypatch, capsys):
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", ids=["DEF-3"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs))
        assert self._file(lr, tree, "--override") == 0
        err = capsys.readouterr().err
        assert "override" in err and "win claims id DEF-3" in err
        assert "| `DEF-3` |" in tree["ledger"].read_text(encoding="utf-8")

    def test_a_dry_run_reports_the_claim_and_writes_nothing(self, lr, tree, monkeypatch, capsys):
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", ids=["DEF-3"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs))
        before = tree["ledger"].read_text(encoding="utf-8")
        assert self._file(lr, tree, "--dry-run") == 0
        assert "win claims id DEF-3" in capsys.readouterr().err
        assert tree["ledger"].read_text(encoding="utf-8") == before

    def test_a_claim_on_the_class_only_is_a_note_and_the_row_lands(self, lr, tree, monkeypatch, capsys):
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", classes=["C1"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs))
        assert self._file(lr, tree) == 0
        err = capsys.readouterr().err
        assert "note" in err and "win claims class C1 on lane/c66" in err and "refused" not in err
        assert "| `DEF-3` |" in tree["ledger"].read_text(encoding="utf-8")

    def test_a_strike_of_a_row_the_other_box_claims_is_refused(self, lr, tree, monkeypatch, capsys):
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", ids=["DEF-1"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs))
        rc = lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"])))
        assert rc == 2
        assert "win claims id DEF-1" in capsys.readouterr().err
        assert "~~`DEF-1`~~" not in tree["ledger"].read_text(encoding="utf-8")

    def test_an_unnamed_box_or_an_absent_channel_reads_nothing(self, lr, tree, monkeypatch, capsys):
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", ids=["DEF-3"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs, machine=None))
        assert self._file(lr, tree) == 0
        assert "claims" not in capsys.readouterr().err
        monkeypatch.setattr(lr, "_mail_module", lambda: None)
        _closed(tree, "DEF-3")
        rc = lr.main(_args(tree, "strike", "DEF-3", "--text-file", str(tree["closing"])))
        assert rc == 0 and "claims" not in capsys.readouterr().err

    def test_an_unread_seat_name_is_a_note_never_a_silent_skip(self, lr, tree, monkeypatch, capsys):
        """A name read that failed (a timeout, a config git cannot parse) is not
        an unnamed box: the claims check was skipped in silence, so a strike of
        a row another seat claims read as checked. The write goes ahead, as it
        does when the channel cannot be read. Dies to: the unread reason taken
        for an unset name."""
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", ids=["DEF-1"])
        channel = _stub_channel(mail, theirs)
        channel.MACHINE_UNREAD = mail.MACHINE_UNREAD
        channel.machine_setting = lambda root, **kw: (
            None, f"{mail.MACHINE_UNREAD} (git config took longer than 10s), so no machine is named")
        monkeypatch.setattr(lr, "_MAIL", channel)
        rc = lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"])))
        err = capsys.readouterr().err
        assert rc == 0, err
        assert "machine name could not be read" in err and "took longer than 10s" in err, err
        assert "claims were not checked" in err
        assert "git config espalier.machine <name>" not in err

    def test_a_two_id_row_is_read_by_every_id_on_its_cell(self, lr, tree, monkeypatch, capsys):
        """A row addressed by one of its ids is the same row to a claim on the
        other (failure-mode review, driven: twenty-one live rows carry more
        than one id)."""
        TestATwoIdRow()._two_id_tree(tree)
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", ids=["LG-9"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs))
        rc = lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"])))
        assert rc == 2
        assert "win claims id LG-9" in capsys.readouterr().err
        assert "~~`DEF-1`" not in tree["ledger"].read_text(encoding="utf-8")

    def test_the_class_verb_refuses_on_a_class_claim(self, lr, tree, monkeypatch, capsys):
        """The verb mints the section: the same class opened on two boxes is
        one id minted twice, so here a class claim refuses, not notes."""
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", classes=["C7"], ids=["DEF-9"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs))
        rc = lr.main(_args(tree, "class", "C7", "--title", "Make X do Y",
                           "--population", "HYGIENE", "--audience", "MAINTAINER"))
        assert rc == 2
        err = capsys.readouterr().err
        assert "refused" in err and "win claims class C7" in err and "minted twice" in err
        assert "C7" not in tree["ledger"].read_text(encoding="utf-8")

    def test_a_channel_present_without_its_sibling_is_a_note_and_a_write(self, lr, tree, monkeypatch, capsys):
        """mail.py imports record_merge at load; a copied subset that has the
        one and not the other raised out of the verb (both reviews, driven).
        The loader runs inside the fail-open now: a note, then the write."""
        def _broken():
            raise ModuleNotFoundError("No module named 'record_merge'")
        monkeypatch.setattr(lr, "_mail_module", _broken)
        assert self._file(lr, tree) == 0
        err = capsys.readouterr().err
        assert "could not be read" in err and "record_merge" in err
        assert "| `DEF-3` |" in tree["ledger"].read_text(encoding="utf-8")

    def test_a_section_typed_with_the_sign_reads_as_the_class(self, lr, tree, monkeypatch, capsys):
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", classes=["C1"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs))
        rc = lr.main(_args(
            tree, "--root", str(tree["ledger"].parents[1]),
            "file", "DEF-3", "--section", "§C1", "--after", "DEF-2",
            "--anchor", "new/site.py::fn", "--text-file", str(tree["body"]), "--severity", "minor",
            "--probe-cmd", "echo open=True", "--open-value", "open=True", "--subject", "body.md",
        ))
        assert rc == 0
        assert "win claims class C1" in capsys.readouterr().err


# ── ids are minted from the seat's block (TP-479 Wave B-1) ───────────────────

_BLOCKS = """# the seat blocks, as the self-host espalier.toml carries them
dispatcher = "air"

[id_blocks]
win = { DEF = "2000-2999", INV = "100-199", TP = "500-599" }
win-2 = { DEF = "3000-3999", INV = "200-299", TP = "600-699" }
_unnamed = { DEF = "1199-1999", INV = "32-99", TP = "479-499" }
"""


def _seat_channel(mail, machine, *claims, inherited=False, clone=None, others=(), clone_reader=None):
    """The mail module as a seat sees it: its name, whether a linked worktree
    inherited that name, its clone's own name (``clone_reader`` replaces that
    read whole), the other machines whose mail refs this clone holds, and the
    live claims (the fold is the real one)."""
    import types
    own_clone = clone if clone is not None else machine
    return types.SimpleNamespace(
        # The real phrase: an unset name ("unnamed") must not read as a failed
        # read, which the mint refuses (code review, TP-701 r7: without it the
        # unread check could be dropped and every unnamed clone refused).
        MACHINE_UNREAD=mail.MACHINE_UNREAD,
        NAME_SCOPES=mail.NAME_SCOPES,   # the mail.py whose clone_machine returns its reason
        machine_setting=lambda root, **kw: (machine, "named" if machine else "unnamed"),
        worktree_name_inherited=lambda root, **kw: inherited,
        clone_machine=clone_reader or (lambda root, **kw: (own_clone, "named" if own_clone else "unnamed")),
        local_mail_machines=lambda root, **kw: list(others),
        read_mail=lambda root, **kw: ({"other": list(claims)}, {}),
        live_claims=mail.live_claims,
        overlapping_claims=mail.overlapping_claims,
    )


def _seat_tree(base: Path, blocks: str | None = _BLOCKS) -> dict:
    base.mkdir(parents=True, exist_ok=True)
    t = _build_tree(base)
    if blocks is not None:
        (base / "espalier.toml").write_text(blocks, encoding="utf-8")
    return t


def _file_minted(lr, t, *pre, rid=()):
    return lr.main(_args(
        t, "--root", str(t["ledger"].parents[1]), *pre,
        "file", *rid, "--section", "C1", "--after", "DEF-2",
        "--anchor", "new/site.py::fn", "--text-file", str(t["body"]), "--severity", "minor",
        "--probe-cmd", "echo open=True", "--open-value", "open=True", "--subject", "body.md",
    ))


def _mint(lr, t, kind, *pre):
    return lr.main(_args(t, "--root", str(t["ledger"].parents[1]), *pre, "mint", "--kind", kind))


def _hand_picked_next(t) -> int:
    """The habit minting replaces: the highest DEF number on the base, plus one."""
    import re
    return max(int(n) for n in re.findall(r"DEF-(\d+)", t["ledger"].read_text(encoding="utf-8"))) + 1


class TestIdsAreMintedFromTheSeatsBlock:
    """``file`` with the id left out mints the lowest free number of this
    seat's block in ``espalier.toml [id_blocks]``; ``mint`` reserves one
    without filing. Two seats filing from one base cannot collide, which the
    old habit of "highest id plus one" does by construction."""

    def test_two_seats_filing_from_one_base_mint_different_ids(self, lr, tmp_path, monkeypatch, capsys):
        mail = _mail_module()
        a, b = _seat_tree(tmp_path / "win"), _seat_tree(tmp_path / "win-2")
        assert _hand_picked_next(a) == _hand_picked_next(b), "the fixture shows the hand-picked collision"
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(mail, "win"))
        assert _file_minted(lr, a) == 0
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(mail, "win-2"))
        assert _file_minted(lr, b) == 0
        assert "| `DEF-2000` |" in a["ledger"].read_text(encoding="utf-8")
        assert "| `DEF-3000` |" in b["ledger"].read_text(encoding="utf-8")
        assert "minted DEF-2000" in capsys.readouterr().err

    def test_a_reservation_holds_its_number_for_the_clone(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        before = t["ledger"].read_text(encoding="utf-8")
        assert _mint(lr, t, "DEF") == 0 and _mint(lr, t, "DEF") == 0
        assert capsys.readouterr().out.split() == ["DEF-2000", "DEF-2001"]
        assert t["ledger"].read_text(encoding="utf-8") == before, "a mint writes no tracked file"
        record = lr.record_path(tmp_path)
        assert json.loads(record.read_text(encoding="utf-8")) == {"DEF": {"2000": "win", "2001": "win"}}
        assert _file_minted(lr, t) == 0, "the filing after them skips both"
        assert "| `DEF-2002` |" in t["ledger"].read_text(encoding="utf-8")
        assert json.loads(record.read_text(encoding="utf-8"))["DEF"]["2002"] == "win"

    def test_a_dry_run_mint_reserves_nothing(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        assert _mint(lr, t, "INV", "--dry-run") == 0 and _mint(lr, t, "INV", "--dry-run") == 0
        assert capsys.readouterr().out.count("INV-100 (dry run: not reserved)") == 2
        assert not lr.record_path(tmp_path).exists()

    def test_a_worktree_seat_mints_from_its_clones_block_and_shares_its_record(self, lr, tmp_path, monkeypatch,
                                                                               capsys):
        """Dies to: a worktree seat with no line of its own refused, or minting
        from its clone's block against a record of its own."""
        a, b = _seat_tree(tmp_path / "main"), _seat_tree(tmp_path / "feat")
        shared = tmp_path / "common" / lr.MINTED_RECORD
        monkeypatch.setattr(lr, "record_path", lambda root: shared)
        mail = _mail_module()
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(mail, "win"))
        assert _mint(lr, a, "DEF") == 0
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(mail, "win-feat", clone="win"))
        assert _file_minted(lr, b) == 0
        captured = capsys.readouterr()
        assert captured.out.splitlines()[0] == "DEF-2000"
        assert "mints from its clone's block (win)" in captured.err
        assert "| `DEF-2001` |" in b["ledger"].read_text(encoding="utf-8")
        assert json.loads(shared.read_text(encoding="utf-8")) == {"DEF": {"2000": "win", "2001": "win-feat"}}

    def test_a_worktree_seat_whose_clone_name_is_unread_is_refused_by_name(self, lr, tmp_path, monkeypatch,
                                                                         capsys):
        """The real clone read, failing. Dies to the failed read taken for a
        clone that names no machine: the mint was then refused as a seat with
        no block, sent to the dispatcher for a block it mints from, and an
        explicit id was judged against no block at all."""
        mail = _mail_module()
        failures = (mail.Unresolvable("git config took longer than 10s"),
                    (128, "", "fatal: bad config line 3 in file .git/config"))
        for i, failed in enumerate(failures):
            t = _seat_tree(tmp_path / str(i))

            def run(argv, _failed=failed, **kw):
                if isinstance(_failed, Exception):
                    raise _failed
                return _failed
            reader = lambda root, _run=run, **kw: mail.clone_machine(root, run=_run)  # noqa: E731
            monkeypatch.setattr(lr, "_MAIL", _seat_channel(mail, "win-feat", clone_reader=reader))
            assert _mint(lr, t, "DEF") != 0
            err = capsys.readouterr().err
            assert "clone's machine name could not be read" in err and mail.MACHINE_UNREAD in err, err
            assert "gives a new seat the next free block" not in err, err
            assert _file_minted(lr, t, rid=("DEF-2005",)) != 0
            err = capsys.readouterr().err
            assert "clone's machine name could not be read" in err and "--override" in err, err

    def test_an_unread_inherited_check_refuses_the_mint_by_name(self, lr, tmp_path, monkeypatch, capsys):
        """mail.worktree_name_inherited answers None where git could not
        answer. Dies to that taken for "has a name of its own": the mint then
        took the clone's next id from a worktree that may share its name."""
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win", inherited=None))
        assert _mint(lr, t, "DEF") != 0
        err = capsys.readouterr().err
        assert "could not be read" in err and "fix it first" in err, err

    def test_a_refused_filing_gives_its_minted_number_back(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        rc = lr.main(_args(
            t, "--root", str(tmp_path), "file", "--section", "C1", "--after", "DEF-2",
            "--anchor", "new/site.py::fn", "--text-file", str(t["body"]), "--severity", "minor",
            "--probe-cmd", "echo closed", "--open-value", "open=True", "--subject", "body.md",
        ))
        assert rc == 2
        assert json.loads(lr.record_path(tmp_path).read_text(encoding="utf-8")) == {"DEF": {}}
        assert _mint(lr, t, "DEF") == 0
        assert capsys.readouterr().out.strip() == "DEF-2000"

    def test_an_unreadable_record_refuses_rather_than_forgets(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        record = lr.record_path(tmp_path)
        record.parent.mkdir(parents=True)
        record.write_text('{"DEF": {"2000": "win"', encoding="utf-8")
        assert _mint(lr, t, "DEF") == 2
        assert "could not be read" in capsys.readouterr().err

    def test_a_live_claim_on_the_next_number_is_skipped(self, lr, tmp_path, monkeypatch, capsys):
        mail = _mail_module()
        t = _seat_tree(tmp_path)
        mine = mail.new_message("win", "claim", "", lane="lane/x", ids=["DEF-2000"])
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(mail, "win", mine))
        assert _mint(lr, t, "DEF") == 0
        assert capsys.readouterr().out.strip() == "DEF-2001"

    def test_a_pack_number_skips_every_pack_file_under_task_packs(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        (tmp_path / "task-packs" / "TP-500-first.md").write_text("x", encoding="utf-8")
        (tmp_path / "task-packs" / "Done").mkdir()
        (tmp_path / "task-packs" / "Done" / "TP-501-second.md").write_text("x", encoding="utf-8")
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        assert _mint(lr, t, "TP") == 0
        assert capsys.readouterr().out.strip() == "TP-502"

    def test_a_seat_name_read_that_failed_refuses_the_mint_by_name(self, lr, tmp_path, monkeypatch, capsys):
        """A timeout, or a config git cannot parse, is not "this clone names no
        machine": that answer offered `git config espalier.machine <name>`,
        which in a worktree renames the clone, or minted from the shared range
        under a false note (both reviewers, TP-701 r6, driven). Dies to: the
        unread read taken for unnamed."""
        t = _seat_tree(tmp_path)
        channel = _seat_channel(_mail_module(), "win", others=("air",))
        channel.MACHINE_UNREAD = "git config could not be read"
        channel.machine_setting = lambda root, **kw: (
            None, "git config could not be read (git config took longer than 10s), so no machine is named")
        monkeypatch.setattr(lr, "_MAIL", channel)
        before = t["ledger"].read_text(encoding="utf-8")
        assert _file_minted(lr, t) == 2
        err = capsys.readouterr().err
        assert "could not be read" in err and "names no machine" not in err, err
        assert "git config espalier.machine <name>" not in err
        assert "retry once git answers" in err, "the refusal names the next step (failure-mode review, r7)"
        assert "cannot parse" in err, "a config git cannot parse never answers by waiting (code review, r8)"
        assert t["ledger"].read_text(encoding="utf-8") == before

    def test_an_explicit_id_is_refused_while_the_seat_name_is_unread(self, lr, tmp_path, monkeypatch, capsys):
        """A cross-block id under an unreadable name is the collision the
        channel exists to refuse; the note the copied-subset case prints let it
        through (failure-mode review, TP-701 r7; dispatcher, c160d6 (A)). Dies
        to: the unread name caught as the copied-subset note."""
        t = _seat_tree(tmp_path)
        channel = _seat_channel(_mail_module(), "win")
        channel.machine_setting = lambda root, **kw: (
            None, "git config could not be read (git config took longer than 10s), so no machine is named")
        monkeypatch.setattr(lr, "_MAIL", channel)
        before = t["ledger"].read_text(encoding="utf-8")
        assert _file_minted(lr, t, rid=("DEF-3001",)) == 2
        err = capsys.readouterr().err
        assert "could not be read" in err and "cannot be checked" in err and "--override" in err, err
        assert t["ledger"].read_text(encoding="utf-8") == before
        # The way past it names is real (both reviewers, r8: untested).
        assert _file_minted(lr, t, "--override", rid=("DEF-3001",)) == 0
        assert "DEF-3001" in t["ledger"].read_text(encoding="utf-8") or any(
            p.name == "DEF-3001.md" for p in t["ledger"].parent.rglob("DEF-3001.md"))

    def test_the_refusal_names_the_steps_the_channel_gives(self, lr, tmp_path, monkeypatch, capsys):
        """The mint refusal prints mail.naming_steps, the one owner of the
        by-hand steps (git's two config changes on a bare clone; TP-701 r5). Dies to:
        the refusal spelling its own copy of the commands."""
        t = _seat_tree(tmp_path)
        channel = _seat_channel(_mail_module(), "win", inherited=True)
        channel.naming_steps = lambda root, **kw: "STEPS-FROM-THE-CHANNEL"
        monkeypatch.setattr(lr, "_MAIL", channel)
        assert _file_minted(lr, t) == 2
        assert "name it first: STEPS-FROM-THE-CHANNEL" in capsys.readouterr().err

    def test_an_inherited_worktree_name_is_refused_with_the_commands(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win", inherited=True))
        before = t["ledger"].read_text(encoding="utf-8")
        assert _file_minted(lr, t) == 2
        err = capsys.readouterr().err
        assert "refused" in err and "answers its clone's name 'win'" in err
        assert "git config extensions.worktreeConfig true" in err
        assert "git config --worktree espalier.machine <name>" in err
        assert t["ledger"].read_text(encoding="utf-8") == before
        assert not lr.record_path(tmp_path).exists()
        # An explicit id from that worktree is refused too: evidence, not a failed read.
        assert _file_minted(lr, t, rid=("DEF-2001",)) == 2
        assert "answers its clone's name 'win'" in capsys.readouterr().err

    def test_an_unnamed_clone_mints_from_the_shared_range_and_says_so(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), None))
        assert _mint(lr, t, "DEF") == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "DEF-1199"
        assert "shared range" in captured.err

    def test_an_unnamed_clone_that_sees_other_machines_is_refused(self, lr, tmp_path, monkeypatch, capsys):
        """Each clone keeps its own record, so the shared range is only safe
        where no other machine writes on this repository."""
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), None, others=("air",)))
        assert _mint(lr, t, "DEF") == 2
        assert "other machines (air)" in capsys.readouterr().err

    def test_a_named_seat_without_a_block_is_sent_to_the_dispatcher(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "air"))
        assert _mint(lr, t, "DEF") == 2
        assert "'air' has no DEF block" in capsys.readouterr().err

    def test_without_a_block_table_a_mint_refuses_and_explicit_ids_file(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path, blocks=None)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        assert _file_minted(lr, t) == 2
        assert "give the id explicitly" in capsys.readouterr().err
        assert _file_minted(lr, t, rid=("DEF-3",)) == 0

    def test_an_explicit_id_must_sit_in_this_seats_block(self, lr, tmp_path, monkeypatch, capsys):
        """Dies to: a hand-picked id outside every block filing silently --
        two worktree seats picking "a safe number" collide at the merge."""
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        assert _file_minted(lr, t, rid=("DEF-3000",)) == 2
        assert "DEF-3000 is in win-2's DEF block" in capsys.readouterr().err
        assert _file_minted(lr, t, rid=("DEF-5000",)) == 2
        assert "outside every DEF block" in capsys.readouterr().err
        assert _file_minted(lr, t, "--override", rid=("DEF-3000",)) == 0
        assert _file_minted(lr, t, rid=("DEF-2005a",)) == 0, "a sub-row in this seat's own block files"
        assert json.loads(lr.record_path(tmp_path).read_text(encoding="utf-8")) == {"DEF": {"2005": "win"}}

    def test_an_explicit_id_another_seat_of_this_clone_reserved_is_refused(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        record = lr.record_path(tmp_path)
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({"DEF": {"2005": "win-feat"}}), encoding="utf-8")
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        before = t["ledger"].read_text(encoding="utf-8")
        assert _file_minted(lr, t, rid=("DEF-2005",)) == 2
        assert "reserved by win-feat" in capsys.readouterr().err
        assert t["ledger"].read_text(encoding="utf-8") == before

    def test_overlapping_blocks_are_refused_by_name(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path, blocks='[id_blocks]\nwin = { DEF = "2000-2999" }\nwin-2 = { DEF = "2500-3499" }\n')
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        assert _mint(lr, t, "DEF") == 2
        assert "overlaps" in capsys.readouterr().err

    def test_a_line_the_scan_cannot_read_is_refused_by_number(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path, blocks='[id_blocks]\nwin = { DEF = "2000-2999" }\nwin-2 = {\n  DEF = "3000" }\n')
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        assert _mint(lr, t, "DEF") == 2
        assert "line 3" in capsys.readouterr().err

    def test_a_mint_waits_for_the_ledger_lock_and_the_record_lock(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        with lr._GEN.ledger_lock(t["ledger"]):
            assert _mint(lr, t, "DEF") == 2
        assert not lr.record_path(tmp_path).exists()
        with lr._record_lock(tmp_path):
            assert _mint(lr, t, "DEF") == 2, "a sibling worktree holding the clone's record"
        assert not lr.record_path(tmp_path).exists()

    @pytest.mark.parametrize("table,ok", [
        ('[id_blocks]\nwin = { DEF = "2000-2999" }  # one {brace} in a comment\n', True),
        ("[id_blocks]\n'win' = { DEF = \"2000-2999\" }\n", True),
        ('[id_blocks]\nwin = { DEF = "2000-2999" }\n[later]\nx = { y = 1 }\n', True),
        ('[id_blocks.win]\nDEF = "2000-2999"\n', False),
        ('[id_blocks]\nwin = { DEF = "2000-2099", DEF = "2100-2199" }\n', False),
    ], ids=["comment-brace", "single-quoted-key", "table-after", "dotted-header", "kind-twice"])
    def test_the_table_scan_edges(self, lr, tmp_path, table, ok):
        (tmp_path / "espalier.toml").write_text(table, encoding="utf-8")
        if ok:
            assert lr.read_id_blocks(tmp_path) == {"win": {"DEF": (2000, 2999)}}
        else:
            with pytest.raises(lr.MintRefused):
                lr.read_id_blocks(tmp_path)


class TestTheRecordLivesInTheClonesGitDirectory:
    """Every worktree of one clone reads one reservation record, found from
    the files git keeps (no spawn)."""

    def test_a_main_checkout_a_linked_worktree_and_a_separate_git_dir(self, lr, tmp_path):
        main = tmp_path / "main"
        (main / ".git" / "worktrees" / "feat").mkdir(parents=True)
        assert lr.record_path(main) == (main / ".git").resolve() / lr.MINTED_RECORD
        wt = tmp_path / "feat"
        wt.mkdir()
        gitdir = main / ".git" / "worktrees" / "feat"
        (wt / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
        (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
        assert lr.record_path(wt) == lr.record_path(main)
        sep = tmp_path / "sep"
        sep.mkdir()
        (tmp_path / "sep.git").mkdir()
        (sep / ".git").write_text(f"gitdir: {tmp_path / 'sep.git'}\n", encoding="utf-8")
        assert lr.record_path(sep) == (tmp_path / "sep.git").resolve() / lr.MINTED_RECORD
        assert lr.record_path(tmp_path / "nowhere") == tmp_path / "nowhere" / lr.MINTED_FALLBACK


class TestTheSelfHostBlockTable:
    """The live table the seats mint from: every seat the protocol names, every
    kind, and the shared range for an unnamed clone. ``read_id_blocks`` refuses
    an overlap, so a clean parse is also the no-overlap pin."""

    def test_the_self_host_table_names_every_seat_and_kind(self, lr):
        blocks = lr.read_id_blocks(REPO_ROOT)
        if blocks is None:
            pytest.skip("this tree's espalier.toml carries no [id_blocks] table")
        for seat in ("win", "win-2", "air", lr.UNNAMED_SEAT):
            assert set(blocks.get(seat, {})) == set(lr.ID_KINDS), seat


# --- a strike reads the base and the head -------------------------------------

#: The fixture's engine check, the shape of ``tests/_engine_check.py``: a child
#: asked from a neutral directory must resolve ``espalier`` to this tree's own
#: package, else the session exits 4 before any test runs. Both trees carry an
#: ``espalier/__init__.py``, so a guard run that does not put the tree first on
#: the child's path resolves the installed engine instead and exits 4 -- on
#: every host of this suite, where ``espalier`` is importable.
_FIXTURE_CONFTEST = '''\
import pathlib
import subprocess
import sys
import tempfile

import pytest


def pytest_sessionstart(session):
    own = pathlib.Path(__file__).resolve().parent.parent / "espalier" / "__init__.py"
    probe = "import importlib.util as u; s = u.find_spec('espalier'); print(s.origin if s and s.origin else '')"
    with tempfile.TemporaryDirectory() as neutral:
        out = subprocess.run([sys.executable, "-c", probe], cwd=neutral, capture_output=True, text=True).stdout.strip()
    if out and pathlib.Path(out).resolve() != own:
        pytest.exit("foreign engine: " + out, returncode=4)
'''

#: The lane's guards, in the head commit only: one earns its red at the base
#: (an assertion), one is green on both trees, one fails at the base by an
#: ImportError (the symbol is new), one by a KeyError (it never reaches its
#: assertion there).
_FIXTURE_GUARDS = '''\
import time

import pkg.mod as m
import pytest


def test_answer():
    assert m.answer() == 2


@pytest.mark.timeout(1)
def test_hangs_on_old_code():
    if m.answer() != 2:
        time.sleep(5)
    assert m.answer() == 2


def test_green_everywhere():
    assert m.answer() in (1, 2)


def test_new_symbol():
    from pkg.mod import answer2
    assert answer2() == 2


def test_table_key():
    assert m.TABLE["new"] == 2
'''

_PROBE_CMD = "python -c \"import pkg.mod as m; print(m.answer())\""
_WALKING_PROBE_CMD = "python -c \"import pathlib; print(len(list(pathlib.Path('.').rglob('mod.py'))))\""


def _mod_source(fixed: bool) -> str:
    if fixed:
        return "TABLE = {'new': 2}\n\n\ndef answer():\n    return 2\n\n\ndef answer2():\n    return 2\n"
    return "TABLE = {}\n\n\ndef answer():\n    return 1\n"


def _two_commit_repo(tmp_path: Path, *, base_fixed: bool = False, head_fixed: bool = True,
                     tip_fixed_after_branch: bool = False, probe_cmd: str = _PROBE_CMD,
                     open_value: str = "1", planted_duplicate: bool = False,
                     ledger_text: str | None = None, def2: dict | None = None,
                     remote: str = "main", origin_head: bool = True) -> dict:
    """A scratch repository with two commits -- the base (``pkg/mod.py``
    unfixed, ``answer()`` printing 1) and the head (fixed, printing 2, with the
    guards) -- and ``origin/main`` plus ``origin/HEAD`` pointing at the base.
    ``tip_fixed_after_branch`` adds a third commit, the base branch gaining the
    fix after the lane branched, and points ``origin/main`` at it; the lane's
    merge-base is still the base. ``planted_duplicate`` leaves an ignored
    ``build/`` holding a copy of ``pkg/mod.py`` in the head checkout."""
    from tests._git_oracle import _git_env
    from tests._quiet_git import NO_BACKGROUND_GIT
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    env = _git_env()

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True,
                              text=True, encoding="utf-8").stdout.strip()

    def write(rel: str, text: str) -> None:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    git("init", "-q")
    git("symbolic-ref", "HEAD", "refs/heads/main")
    for key, value in (*NO_BACKGROUND_GIT, ("user.email", "t@example.com"), ("user.name", "t"),
                       ("commit.gpgsign", "false")):
        git("config", key, value)
    write("pkg/__init__.py", "")
    write("pkg/mod.py", _mod_source(base_fixed))
    write("espalier/__init__.py", "")
    write("tests/conftest.py", _FIXTURE_CONFTEST)
    write("pyproject.toml", "[tool.pytest.ini_options]\n")
    write(".gitignore", "build/\n__pycache__/\n")
    write("task-packs/FORWARD_LEDGER.md", ledger_text or _ledger())
    write("task-packs/LEDGER_PROBES.json", json.dumps({"probes": [
        {"id": "DEF-1", "subject": "pkg/mod.py", "cmd": probe_cmd, "open_value": open_value,
         "why_not": None, "row_sha": "x"},
        def2 or {"id": "DEF-2", "subject": "site", "cmd": "echo b", "open_value": "b", "why_not": None,
                 "row_sha": "y"},
    ]}, indent=1) + "\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = git("rev-parse", "HEAD")
    write("pkg/mod.py", _mod_source(head_fixed))
    write("tests/test_guard.py", _FIXTURE_GUARDS)
    git("add", "-A")
    git("commit", "-q", "-m", "head")
    head = git("rev-parse", "HEAD")
    tip = base
    if tip_fixed_after_branch:
        git("checkout", "-q", "--detach", base)
        write("pkg/mod.py", _mod_source(True))
        git("add", "-A")
        git("commit", "-q", "-m", "the base gains the fix after the lane branched")
        tip = git("rev-parse", "HEAD")
        git("checkout", "-q", "main")
    git("update-ref", f"refs/remotes/origin/{remote}", tip)
    if origin_head:
        git("symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{remote}")
    if planted_duplicate:
        write("build/pkg/mod.py", _mod_source(head_fixed))
    closing = tmp_path / "closing.md"
    closing.write_text("landed with the probe read on both sides", encoding="utf-8")
    return {"repo": repo, "base": base, "head": head, "tip": tip, "closing": closing,
            "ledger": repo / "task-packs" / "FORWARD_LEDGER.md",
            "probes": repo / "task-packs" / "LEDGER_PROBES.json"}


def _repo_args(r: dict, *rest: str) -> list[str]:
    return ["--root", str(r["repo"]), "--date", "2026-10-25", *rest]


def _files(r: dict) -> tuple[str, str]:
    return r["ledger"].read_text(encoding="utf-8"), r["probes"].read_text(encoding="utf-8")


class TestAStrikeReadsTheBaseAndTheHead:
    """The strike drives the row's probe at the merge-base and at the head
    before it writes, and runs each ``--guard`` on both sides: red at the base
    with the head's ``tests/`` laid over it, green at the head. Each test names
    the mutation it dies to (tests/CLAUDE.md rule 1); a refusal writes neither
    file. The replays behind the shape (2026-10-25, five struck rows): every
    pre-strike probe read open at the base, and two of the five still read
    open at the lane head, which only the head drive refuses."""

    def test_a_true_strike_reads_open_at_the_base_and_closed_at_the_head(self, lr, tmp_path, capsys):
        """Mutation: a strike that drives nothing prints no reading."""
        r = _two_commit_repo(tmp_path)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]))) == 0
        err = capsys.readouterr().err
        assert f"STILL_OPEN at the base {r['base'][:12]}" in err and "STRIKE_CANDIDATE at the head" in err
        assert "| ~~`DEF-1`~~ |" in r["ledger"].read_text(encoding="utf-8")

    def test_a_probe_already_closed_at_the_base_refuses_naming_the_base(self, lr, tmp_path, capsys):
        """Mutation: the base drive removed, so a row whose probe never read
        open where the row said the defect was is struck on the head alone."""
        r = _two_commit_repo(tmp_path, base_fixed=True)
        before = _files(r)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]))) == 2
        err = capsys.readouterr().err
        assert f"did not read its open value at the base {r['base'][:12]}" in err and "--no-base" in err
        assert _files(r) == before and not list(r["probes"].parent.glob("*.pending"))

    def test_a_probe_still_open_at_the_head_refuses(self, lr, tmp_path, capsys):
        """Mutation: the head drive removed, so a row whose probe still prints
        its open value on the lane is struck (two of five replayed strikes)."""
        r = _two_commit_repo(tmp_path, head_fixed=False)
        before = _files(r)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]))) == 2
        assert "reads its open value '1' at the head too" in capsys.readouterr().err
        assert _files(r) == before

    def test_the_base_is_the_merge_base_not_the_tip(self, lr, tmp_path, capsys):
        """Mutation: the base taken as origin/main's tip, so a fix another lane
        merged after this one branched refuses a true strike."""
        r = _two_commit_repo(tmp_path, tip_fixed_after_branch=True)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]))) == 0
        err = capsys.readouterr().err
        assert f"STILL_OPEN at the base {r['base'][:12]}" in err and r["tip"][:12] not in err

    def test_an_explicit_base_is_resolved_as_given(self, lr, tmp_path, capsys):
        """Mutation: ``--base`` ignored in favour of the default."""
        r = _two_commit_repo(tmp_path, tip_fixed_after_branch=True)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]),
                                  "--base", r["tip"])) == 2
        assert f"did not read its open value at the base {r['tip'][:12]}" in capsys.readouterr().err

    def test_an_undrivable_probe_is_one_line_by_default_and_a_refusal_under_an_explicit_base(
            self, lr, tmp_path, capsys):
        """The verdict decides, never a word match: DEF-2's subject is on
        neither tree, so the runner reads UNRESOLVED on both. Mutation: the
        undrivable read dropped (a refusal with no flag, or a strike with one)."""
        r = _two_commit_repo(tmp_path)
        assert lr.main(_repo_args(r, "strike", "DEF-2", "--text-file", str(r["closing"]))) == 0
        err = capsys.readouterr().err
        assert f"could not be driven at the base {r['base'][:12]}" in err and "subject missing: site" in err
        assert "could not be driven at the head" in err
        r = _two_commit_repo(tmp_path / "second")
        assert lr.main(_repo_args(r, "strike", "DEF-2", "--text-file", str(r["closing"]),
                                  "--base", "origin/main")) == 2
        assert "and --base asks for the drive" in capsys.readouterr().err

    def test_a_row_with_no_probe_command_is_said_and_refused_only_under_an_explicit_base(
            self, lr, tmp_path, capsys):
        """A ``why_not`` row has no command, so neither side is read: its reason
        is said once, and an explicit ``--base`` refuses it. Mutation: a row with
        no command skipped silently, or refused with no flag."""
        def2 = {"id": "DEF-2", "subject": "site", "cmd": None, "open_value": None,
                "why_not": "an intermittent red has no steady open value", "row_sha": "y"}
        r = _two_commit_repo(tmp_path, def2=def2)
        assert lr.main(_repo_args(r, "strike", "DEF-2", "--text-file", str(r["closing"]))) == 0
        assert "no probe command (an intermittent red" in capsys.readouterr().err
        r = _two_commit_repo(tmp_path / "second", def2=def2)
        assert lr.main(_repo_args(r, "strike", "DEF-2", "--text-file", str(r["closing"]),
                                  "--base", "origin/main")) == 2
        assert "and --base asks for the drive" in capsys.readouterr().err

    def test_no_base_skips_the_base_drive_and_says_so(self, lr, tmp_path, capsys):
        """Mutation: ``--no-base`` skipping the drive silently."""
        r = _two_commit_repo(tmp_path, base_fixed=True)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]), "--no-base")) == 0
        err = capsys.readouterr().err
        assert "the base was not read (--no-base)" in err and "STILL_OPEN at the base" not in err

    def test_a_tree_with_no_remote_proceeds_with_one_printed_line(self, lr, tree, capsys):
        """The default on a plain directory, an adopter's clone with no remote
        among them: the base is said to be unread, the head is still driven,
        and the strike proceeds. Mutation: the default-on base drive refusing
        where no base resolves."""
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        err = capsys.readouterr().err
        assert "the base was not read (no origin/HEAD, origin/main or origin/master" in err
        assert "could not be driven at the head" in err

    def test_the_head_verdict_is_the_heads_not_the_base_memo(self, lr, tmp_path, capsys):
        """The base tree is pristine (checked out from a ref: no generated
        duplicate), the head is this checkout, where an ignored ``build/``
        holds a copy of the probe's subject, so a tree-walking probe reads
        UNRESOLVED there. Mutation: the runner rooted by a bare ``_ROOT``
        assignment, so the base's empty memo leaks into the head drive and
        the walk answers over the duplicate."""
        r = _two_commit_repo(tmp_path, probe_cmd=_WALKING_PROBE_CMD, planted_duplicate=True)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]))) == 0
        err = capsys.readouterr().err
        assert f"STILL_OPEN at the base {r['base'][:12]}" not in err  # no pair line: the head was unread
        assert "could not be driven at the head" in err and "cannot be trusted while build/" in err

    def test_every_id_of_a_multi_id_cell_is_driven(self, lr, tmp_path, capsys):
        """Mutation: the drive covers the id typed, not the co-ids the cell
        closes with it (``DEF-863``'s both-or-neither rule)."""
        ledger = _ledger(c1_rows=("| `DEF-1` `DEF-2` | site | what | major |",),
                         appendix=("| `DEF-1` | §C1 | site |", "| `DEF-2` | §C1 | site |"))
        def2 = {"id": "DEF-2", "subject": "pkg/mod.py", "cmd": "python -c \"print('x')\"", "open_value": "x",
                "why_not": None, "row_sha": "y"}
        r = _two_commit_repo(tmp_path, ledger_text=ledger, def2=def2)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]))) == 2
        assert "the probe of DEF-2 reads its open value 'x' at the head too" in capsys.readouterr().err

    def test_a_guard_red_at_the_base_and_green_at_the_head_strikes(self, lr, tmp_path, capsys):
        """Mutations: the guard run at the head only; the head's ``tests/``
        not laid over the base (the guard is absent there, exit 4 or 5);
        PYTHONPATH not set on either run (the fixture's engine check exits 4
        wherever ``espalier`` is importable from elsewhere, as on every host of
        this suite)."""
        r = _two_commit_repo(tmp_path)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]),
                                  "--guard", "tests/test_guard.py::test_answer")) == 0
        err = capsys.readouterr().err
        assert (f"the guard tests/test_guard.py::test_answer is red at the base {r['base'][:12]} "
                "(AssertionError) and green at the head") in err

    def test_a_guard_green_on_both_sides_refuses_as_indistinguishable(self, lr, tmp_path, capsys):
        """A fix that lives under ``tests/`` rides the overlay to the base, and
        so does a guard that does not read the defect; neither earns a red.
        Mutation: the base run dropped, so green at the head is enough."""
        r = _two_commit_repo(tmp_path)
        before = _files(r)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]),
                                  "--guard", "tests/test_guard.py::test_green_everywhere")) == 2
        err = capsys.readouterr().err
        assert f"is green at the base {r['base'][:12]} too" in err and "cannot tell the two trees apart" in err
        assert _files(r) == before

    def test_a_guard_red_at_the_head_refuses(self, lr, tmp_path, capsys):
        """The lane has not fixed what the guard reads: the probe and the guard
        refuse, each by name. Mutation: the head run's verdict unread (code
        review, 2026-10-25: the first cut of this test passed ``--no-base`` and
        the base refusal alone satisfied it)."""
        r = _two_commit_repo(tmp_path, head_fixed=False)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]),
                                  "--guard", "tests/test_guard.py::test_answer")) == 2
        err = capsys.readouterr().err
        assert "is red at the head (AssertionError)" in err and "reads its open value '1' at the head too" in err

    @pytest.mark.skipif(sys.platform == "win32",
                        reason="pytest-timeout's thread method ends the whole run on Windows, so the "
                               "refusal there is the no-record one")
    def test_a_guard_that_hangs_on_the_unfixed_code_is_not_an_earned_red(self, lr, tmp_path, capsys):
        """pytest-timeout ends a hung test with ``pytest.fail``, so its exception
        is ``Failed`` like an earned red's; the message tells them apart.
        Mutation: the timeout message unread, so a guard that hangs at the base
        strikes (code review, 2026-10-25)."""
        r = _two_commit_repo(tmp_path)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]),
                                  "--guard", "tests/test_guard.py::test_hangs_on_old_code")) == 2
        err = capsys.readouterr().err
        assert "hung at the base" in err and "Timeout" in err

    def test_a_row_with_no_probe_entry_is_said_and_refused_under_an_explicit_base(self, lr, tmp_path, capsys):
        """Mutation: a row the roster never heard of skipped with one line under
        a flag that asked for the drive (code review, 2026-10-25)."""
        other = {"id": "DEF-9", "subject": "site", "cmd": "echo b", "open_value": "b", "why_not": None,
                 "row_sha": "y"}
        r = _two_commit_repo(tmp_path, def2=other)
        assert lr.main(_repo_args(r, "strike", "DEF-2", "--text-file", str(r["closing"]))) == 0
        assert "DEF-2 carries no probe entry" in capsys.readouterr().err
        r = _two_commit_repo(tmp_path / "second", def2=other)
        assert lr.main(_repo_args(r, "strike", "DEF-2", "--text-file", str(r["closing"]),
                                  "--base", "origin/main")) == 2
        assert "carries no probe entry, and --base asks for the drive" in capsys.readouterr().err

    def test_an_explicit_base_this_clone_does_not_hold_refuses_naming_it(self, lr, tmp_path, capsys):
        """Mutation: an unresolvable ``--base`` read as no base and skipped."""
        r = _two_commit_repo(tmp_path)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]),
                                  "--base", "nowhere")) == 2
        assert "the base could not be read (this clone does not hold nowhere)" in capsys.readouterr().err

    def test_the_default_base_falls_back_to_origin_master_with_no_origin_head(self, lr, tmp_path, capsys):
        """Mutation: the fallback dropped, so a clone whose remote recorded no
        HEAD and names ``master`` reads no base."""
        r = _two_commit_repo(tmp_path, remote="master", origin_head=False)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]))) == 0
        assert f"STILL_OPEN at the base {r['base'][:12]}" in capsys.readouterr().err

    def test_a_base_that_cannot_be_checked_out_refuses(self, lr, tmp_path, monkeypatch, capsys):
        """Mutation: a failed checkout read as an empty base, every probe
        UNRESOLVED there with one note each."""
        r = _two_commit_repo(tmp_path)

        def broken(root, sha, scratch):
            raise lr.BaseUnavailable(f"git read-tree of {sha[:12]} exited 128: forced")

        monkeypatch.setattr(lr, "_base_tree", broken)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]))) == 2
        assert "could not be checked out (git read-tree" in capsys.readouterr().err

    def test_a_guard_whose_base_failure_is_an_import_error_refuses(self, lr, tmp_path, capsys):
        """Mutation: the exception read dropped, so a guard that fails at the
        base because the lane's symbol does not exist there counts as red."""
        r = _two_commit_repo(tmp_path)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]),
                                  "--guard", "tests/test_guard.py::test_new_symbol")) == 2
        err = capsys.readouterr().err
        assert "ImportError" in err and "proves only that the lane's symbol is new" in err

    def test_a_guard_that_does_not_reach_its_assertion_at_the_base_refuses(self, lr, tmp_path, capsys):
        """pytest's report carries no exception type (measured: a ``<failure
        message="assert 1 == 2">`` with no ``type``), so the strike's own plugin
        records it; an earned red fails by AssertionError or pytest.fail, and a
        KeyError at the base is a test that never reached its assertion. Mutation:
        any exit 1 at the base read as the red."""
        r = _two_commit_repo(tmp_path)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]),
                                  "--guard", "tests/test_guard.py::test_table_key")) == 2
        err = capsys.readouterr().err
        assert "KeyError" in err and "did not reach its assertion at the base" in err

    def test_a_guard_that_does_not_collect_refuses_naming_the_exit(self, lr, tmp_path, capsys):
        """Mutation: a usage error (exit 4) or nothing collected (exit 5) read
        as a verdict."""
        r = _two_commit_repo(tmp_path)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]),
                                  "--guard", "tests/test_guard.py::test_nope")) == 2
        assert "does not run at the head (pytest exit 4" in capsys.readouterr().err

    def test_a_guard_with_no_readable_base_refuses(self, lr, tmp_path, capsys):
        """Mutation: a guard run at the head alone when the base is unread."""
        r = _two_commit_repo(tmp_path)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]), "--no-base",
                                  "--guard", "tests/test_guard.py::test_answer")) == 2
        assert "--guard needs the base tree" in capsys.readouterr().err

    def test_a_guard_that_outruns_its_bound_refuses(self, lr, tmp_path, monkeypatch, capsys):
        """Mutation: a timeout read as green or as red."""
        r = _two_commit_repo(tmp_path)
        monkeypatch.setattr(lr, "_GUARD_TIMEOUT", 0.01)
        assert lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"]),
                                  "--guard", "tests/test_guard.py::test_answer")) == 2
        assert "did not finish within 0.01 s" in capsys.readouterr().err

    def test_the_guard_child_runs_with_the_tree_first_and_the_box_lock_stripped(self, lr, tmp_path, monkeypatch):
        """The child's environment: the tree first on PYTHONPATH (the engine
        check resolves ``espalier`` there), the plugin's directory next, the
        parent's path after; no bytecode written into either tree; the box
        lock's two variables and the session marker gone. Mutation: a
        variable left in, or the tree not first."""
        for key, value in (("ESPALIER_BOX_LOCK", "/l"), ("ESPALIER_BOX_LOCK_HOLDER", "p"), ("CLAUDECODE", "1"),
                           ("PYTHONPATH", "/elsewhere")):
            monkeypatch.setenv(key, value)
        env = lr._guard_env(tmp_path / "tree", tmp_path / "plugin", tmp_path / "report.json")
        assert env["PYTHONPATH"] == os.pathsep.join([str(tmp_path / "tree"), str(tmp_path / "plugin"), "/elsewhere"])
        assert not any(k.startswith("ESPALIER_BOX_LOCK") for k in env) and "CLAUDECODE" not in env
        assert env["PYTHONDONTWRITEBYTECODE"] == "1" and env["ESPALIER_GUARD_REPORT"] == str(tmp_path / "report.json")

    def test_a_dry_run_drives_both_sides_and_shows_the_refusal(self, lr, tmp_path, capsys):
        """The dry run must show the refusal rather than a row it would never
        write (the deferrals' rule). Mutation: the drive skipped under --dry-run."""
        r = _two_commit_repo(tmp_path, head_fixed=False)
        assert lr.main(_repo_args(r, "--dry-run", "strike", "DEF-1", "--text-file", str(r["closing"]))) == 2
        assert "reads its open value '1' at the head too" in capsys.readouterr().err


#: A probe that reads the checkout alone: ``.git`` is there and not in the
#: export. Read without asking git, so a temp folder that sits inside some
#: other repository cannot answer for the export.
_DOT_GIT_PROBE_CMD = "python -c \"import os; print(os.path.exists('.git'))\""


class TestAFilingDrivesTheProbeWhereAStrikeWill:
    """``DEF-5045``. ``file`` drove a new row's probe in the checkout alone,
    which holds ``.git``, while ``strike`` drives it at the base in
    ``_base_tree``'s export, which does not; so a probe that read the tree
    through git filed cleanly and could be struck only with ``--no-base``
    (``DEF-4074``'s was). ``file``, and ``repin`` where it changes the probe,
    now drive it in the export of HEAD too and refuse a probe whose two
    readings disagree, ``--no-base`` the named way past. Each test names the
    mutation it dies to; a refusal writes neither file."""

    def _file(self, lr, r, tmp_path, *extra, pre=(), probe_cmd=_DOT_GIT_PROBE_CMD, open_value="True"):
        body = tmp_path / "body.md"
        body.write_text("**A probe read where the row is filed.**", encoding="utf-8")
        return lr.main(_repo_args(r, *pre, "file", "DEF-3", "--section", "C1", "--after", "DEF-2",
                                  "--anchor", "pkg/mod.py::answer", "--text-file", str(body),
                                  "--severity", "minor", "--probe-cmd", probe_cmd,
                                  "--open-value", open_value, "--subject", "pkg/mod.py", *extra))

    @staticmethod
    def _entry(r, rid: str) -> dict:
        return next(p for p in json.loads(r["probes"].read_text(encoding="utf-8"))["probes"] if p["id"] == rid)

    def test_a_probe_that_reads_the_checkout_alone_is_refused_naming_both_readings(self, lr, tmp_path, capsys):
        """Mutation: the export drive removed, so the row files here and its
        strike refuses at the base after the fix is done."""
        r = _two_commit_repo(tmp_path)
        before = _files(r)
        assert self._file(lr, r, tmp_path) == 2
        err = capsys.readouterr().err
        assert "reads its open value 'True' in this checkout and prints another value" in err
        assert f"in the export of HEAD {r['head'][:12]} (prints 'False'" in err
        assert "--no-base" in err and "nothing filed" in err
        # espalier/cli.py reads a filing whose stderr holds the verdict's word as satisfied
        assert "STRIKE_CANDIDATE" not in err
        assert _files(r) == before

    def test_the_dry_run_drives_the_export_and_shows_the_refusal(self, lr, tmp_path, capsys):
        """Mutation: the export drive skipped under --dry-run."""
        r = _two_commit_repo(tmp_path)
        assert self._file(lr, r, tmp_path, pre=("--dry-run",)) == 2
        assert "in the export of HEAD" in capsys.readouterr().err

    def test_no_base_files_it_says_so_and_the_stamp_records_it(self, lr, tmp_path, capsys):
        """Mutation: --no-base ignored (the refusal stands), or honoured with
        nothing said and nothing recorded for the strike to read."""
        r = _two_commit_repo(tmp_path)
        assert self._file(lr, r, tmp_path, "--no-base") == 0
        assert "not driven in the export of HEAD (--no-base)" in capsys.readouterr().err
        assert self._entry(r, "DEF-3")["verified_2026_10_25"] == (
            "OPEN (filed 2026-10-25; probe driven at filing here; the export of HEAD not driven: --no-base)")

    def test_a_probe_that_reads_the_tree_files_and_the_stamp_names_both_trees(self, lr, tmp_path, capsys):
        """Mutation: a refusal where the two readings agree."""
        r = _two_commit_repo(tmp_path)
        assert self._file(lr, r, tmp_path, probe_cmd=_PROBE_CMD, open_value="2") == 0
        assert "nothing filed" not in capsys.readouterr().err
        assert self._entry(r, "DEF-3")["verified_2026_10_25"] == (
            f"OPEN (filed 2026-10-25; probe driven at filing here and in the export of HEAD {r['head'][:12]})")

    def test_an_input_only_the_working_tree_holds_is_a_note_and_files(self, lr, tmp_path, capsys):
        """The export holds committed files only: a declared input this
        checkout alone carries reads UNRESOLVED there, which the strike's base
        drive notes and never refuses by default, so the filing notes it too
        (refusing it stopped ``init`` filing its onboarding rows). Mutation: an
        undrivable export refused, or passed with nothing said or recorded."""
        r = _two_commit_repo(tmp_path)
        (r["repo"] / "local.txt").write_text("held here alone", encoding="utf-8")
        assert self._file(lr, r, tmp_path, "--inputs", "local.txt", probe_cmd=_PROBE_CMD, open_value="2") == 0
        err = capsys.readouterr().err
        assert "and UNRESOLVED in the export of HEAD" in err and "input missing: local.txt" in err
        assert "a later strike passes with --no-base" in err
        assert self._entry(r, "DEF-3")["verified_2026_10_25"] == (
            f"OPEN (filed 2026-10-25; probe driven at filing here; UNRESOLVED in the export of HEAD "
            f"{r['head'][:12]})")

    def test_a_root_that_is_not_its_own_checkout_is_one_note_and_files(self, lr, tree, capsys):
        """Mutation: a root with no HEAD to export refused, or passed in silence."""
        assert lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]),
                             "file", "DEF-3", "--section", "C1", "--after", "DEF-2",
                             "--anchor", "new/site.py::fn", "--text-file", str(tree["body"]),
                             "--severity", "minor", "--probe-cmd", "echo open=True",
                             "--open-value", "open=True", "--subject", "body.md")) == 0
        assert "not driven in the export of HEAD" in capsys.readouterr().err
        entry = next(p for p in json.loads(tree["probes"].read_text(encoding="utf-8"))["probes"] if p["id"] == "DEF-3")
        assert entry["verified_2026_09_06"].startswith(
            "OPEN (filed 2026-09-06; probe driven at filing here; the export of HEAD not driven: ")

    def test_a_repin_to_a_probe_that_reads_the_checkout_alone_is_refused_and_no_base_passes(
            self, lr, tmp_path, capsys):
        """``repin`` writes a probe a strike will drive, as ``file`` does.
        Mutation: the repin's export drive removed, or --no-base not honoured."""
        r = _two_commit_repo(tmp_path)
        before = _files(r)
        argv = ("repin", "DEF-1", "--probe-cmd", _DOT_GIT_PROBE_CMD, "--open-value", "True", "--reason", "re-aimed")
        assert lr.main(_repo_args(r, *argv)) == 2
        err = capsys.readouterr().err
        assert "in the export of HEAD" in err and "nothing re-pinned" in err
        assert _files(r) == before
        assert lr.main(_repo_args(r, *argv, "--no-base")) == 0
        assert "not driven in the export of HEAD (--no-base)" in capsys.readouterr().err

    def test_a_repin_that_leaves_the_probe_alone_does_not_drive_the_export(self, lr, tmp_path, capsys):
        """A re-grade of a row whose probe already reads the checkout alone
        changes nothing a strike will drive. Mutation: every repin drives the
        export, so a severity change is refused over a probe it did not touch."""
        r = _two_commit_repo(tmp_path, probe_cmd=_DOT_GIT_PROBE_CMD, open_value="True")
        assert lr.main(_repo_args(r, "repin", "DEF-1", "--severity", "nit", "--reason", "re-graded")) == 0
        assert "export of HEAD" not in capsys.readouterr().err

    def test_a_head_that_cannot_be_exported_refuses_naming_no_base(self, lr, tmp_path, monkeypatch, capsys):
        """Mutation: a failed export read as agreement, so the filing passes on
        one reading."""
        r = _two_commit_repo(tmp_path)

        def broken(*_a, **_k):
            raise lr.BaseUnavailable("git read-tree exited 128")
        monkeypatch.setattr(lr, "_base_tree", broken)
        assert self._file(lr, r, tmp_path, probe_cmd=_PROBE_CMD, open_value="2") == 2
        err = capsys.readouterr().err
        assert "could not be exported" in err and "git read-tree exited 128" in err and "--no-base" in err

    def test_the_filing_and_the_strike_read_the_export_through_one_drive(self, lr, tmp_path, monkeypatch):
        """Mutation: either verb drives its export some other way, so a change
        to how the strike reads its base leaves the filing's reading behind."""
        r = _two_commit_repo(tmp_path)
        seen: list[list[str]] = []
        real = lr._drive_in_export

        def spy(tree, probes):
            seen.append(sorted(probes))
            return real(tree, probes)
        monkeypatch.setattr(lr, "_drive_in_export", spy)
        assert self._file(lr, r, tmp_path, probe_cmd=_PROBE_CMD, open_value="2") == 0
        lr.main(_repo_args(r, "strike", "DEF-1", "--text-file", str(r["closing"])))
        assert seen == [["probe"], ["DEF-1"]]

    @pytest.mark.parametrize("flag", [("--subject", "pkg/mod.py"), ("--inputs", "pkg/__init__.py")])
    def test_a_repin_that_names_only_a_subject_or_inputs_drives_the_export(self, lr, tmp_path, capsys, flag):
        """Mutation: the repin's gate reads the command and the value alone."""
        r = _two_commit_repo(tmp_path, probe_cmd=_DOT_GIT_PROBE_CMD, open_value="True")
        assert lr.main(_repo_args(r, "repin", "DEF-1", *flag, "--reason", "re-anchored")) == 2
        assert "prints another value in the export of HEAD" in capsys.readouterr().err

    def test_no_base_beside_why_not_is_refused_by_name(self, lr, tree, capsys):
        """Mutation: the flag accepted on a row that drives nothing."""
        with pytest.raises(SystemExit):
            lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]),
                          "file", "DEF-3", "--section", "C1", "--after", "DEF-2",
                          "--anchor", "new/site.py::fn", "--text-file", str(tree["body"]),
                          "--severity", "minor", "--subject", "body.md",
                          "--why-not", "no local oracle", "--no-base"))
        assert "--no-base skips a drive" in capsys.readouterr().err
