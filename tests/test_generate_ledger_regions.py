"""Contract for ``scripts/generate_ledger_regions.py`` -- and the gate that makes it matter.

The ledger claimed four times over to be generated and had no generator, so five
of its summary regions drifted. A generator alone would not have fixed that: it
would have been a sixth thing nobody runs. ``TestTheLiveLedgerConverges`` is the
actual repair -- it runs ``--check`` against the real ledger inside the suite, so
drift cannot land green.

That is the same shape ``tests/test_doc_regions.py`` gives
``scripts/generate_doc_regions.py``.

The synthetic tests below drive the derivation on hand-built trees. They exist
because the live gate can only ever say "converged" or "not"; it cannot show that
each rule fires for its own reason, and a rule that never fires is
indistinguishable from one that cannot.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = REPO_ROOT / "scripts" / "generate_ledger_regions.py"

if not _SCRIPT.is_file():  # pragma: no cover - adopter tree
    pytest.skip(
        "scripts/generate_ledger_regions.py is self-host dev tooling",
        allow_module_level=True,
    )

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import generate_ledger_regions as gen  # noqa: E402

# full-tree-exempt: the live-tree tests here (TestTheLiveLedgerConverges, and
# TestTheFloorsAreDerivedFromTheRecord's record-file pin) read task-packs/, which
# a release export prunes; each skips itself by name when its file is absent, so
# the module needs no _FULL_TREE_NODEIDS entry (TP-452 1-D, 2026-09-20).


# --------------------------------------------------------------------------
# A synthetic ledger. Small, but the same GRAMMAR the real file uses.
# --------------------------------------------------------------------------

def _ledger(
    *,
    headline: int = 2,
    c1_cell: str = "2",
    c1_members: int = 2,
    c1_rows: tuple[str, ...] = ("| `DEF-1` | site | what | major |",
                               "| `DEF-2` | site | what | minor |"),
    appendix: tuple[str, ...] = ("| `DEF-1` | §C1 | site |",
                                 "| `DEF-2` | §C1 | site |"),
    c1_tags: tuple[str, str] = ("LOGIC_BUG", "ADOPTER"),
    split: tuple[int, int, int] = (2, 0, 0),
    adopter: int = 2,
    pop_table: dict[str, int] | None = None,
    aud_table: dict[str, int] | None = None,
    mixed: bool = False,
    c2_rows: tuple[str, ...] = ("| `DEF-3` | site | what | nit | HYGIENE | MAINTAINER |",),
) -> str:
    """The synthetic ledger. ``mixed=True`` adds a MIXED class (§C2, the §C0
    shape) whose rows carry their own ``pop | aud`` cells; the caller then
    owns the split, the adopter figure and the tables, which default to the
    two-row §C1-only composition."""
    pop_table = {"LOGIC_BUG": split[0], "HYGIENE": split[1], "OPERATOR_ACTION": split[2]} \
        if pop_table is None else pop_table
    aud_table = {"ADOPTER": adopter, "MAINTAINER": 0, "OPERATOR": 0} \
        if aud_table is None else aud_table
    rows = "\n".join(c1_rows)
    idx = "\n".join(appendix)
    pop_rows = "\n".join(f"| {k} | {v} | meaning |" for k, v in pop_table.items())
    aud_rows = "\n".join(
        (f"| **{k}** — someone who ran `pip install espalier` | **{v}** |" if k == "ADOPTER"
         else f"| {k} | {v} |") for k, v in aud_table.items()
    )
    c2_index = "\n| [§C2](#c2) | Standalone | " + str(len(c2_rows)) + " | MIXED | MIXED | — |" if mixed else ""
    c2_section = ("\n### §C2 - Standalone\n\n**Members (" + str(len(c2_rows)) + ")** - derived, never typed\n\n"
                  "| id | site | what | sev | pop | aud |\n|---|---|---|---|---|---|\n" + "\n".join(c2_rows) + "\n"
                  ) if mixed else ""
    c2_appendix = "\n" + "\n".join(
        f"| `{r.split('`')[1]}` | §C2 | site |" for r in c2_rows) if mixed else ""
    # A class MIXED on an axis carries 6-cell rows, so its header says so too;
    # the parsers ignore headers, but a fixture whose header disagrees with its
    # rows is the shape the next copy-forward spreads (failure-mode pass, 2026-09-20).
    c1_header = ("| id | site | what | sev | pop | aud |\n|---|---|---|---|---|---|"
                 if "MIXED" in c1_tags else "| id | site | what | sev |\n|---|---|---|---|")
    c1_live = sum(1 for r in c1_rows if not r.lstrip("| ").startswith("~~"))
    c2_live = sum(1 for r in c2_rows if not r.lstrip("| ").startswith("~~")) if mixed else 0
    live = c1_live + c2_live
    n_classes = 1 if c1_live else 0
    return f"""# Forward Ledger

**Live: {headline}** — {split[0]} logic bugs · {split[1]} hygiene · {split[2]} operator actions.
**{adopter}** reach an adopter. Counted apart on purpose.

## §2 - Open fixes, by unit of work ({live} LIVE issues in {n_classes} classes + {c2_live} standalone)

| population | live | what it means |
|---|---|---|
{pop_rows}

| audience | live |
|---|---|
{aud_rows}

### Class index

| § | class | members | population | audience | effort |
|---|---|---|---|---|---|
| [§C1](#c1) | A class | {c1_cell} | {c1_tags[0]} | {c1_tags[1]} | ~1 LOC |{c2_index}

### §C1 - A class

**Members ({c1_members})** - derived, never typed

{c1_header}
{rows}
{c2_section}
## Appendix B - id index

| id | § | site |
|---|---|---|
{idx}{c2_appendix}
"""


def _regions(monkeypatch, text: str) -> list[dict]:
    """``find_drift`` over a synthetic tree, with the probe file neutralised."""
    monkeypatch.setattr(gen, "_probe_ids", lambda: set())
    return gen.find_drift(text)


def _kinds(drift: list[dict]) -> set[str]:
    return {d["region"] for d in drift}


class TestEachRuleFiresForItsOwnReason:
    def test_a_converged_ledger_reports_nothing(self, monkeypatch):
        assert _regions(monkeypatch, _ledger()) == []

    def test_a_stale_headline_is_reported(self, monkeypatch):
        drift = _regions(monkeypatch, _ledger(headline=99))
        assert "headline" in _kinds(drift)
        assert any("99" in d["detail"] and "2" in d["detail"] for d in drift)

    def test_a_members_line_disagreeing_with_its_rows_is_reported(self, monkeypatch):
        drift = _regions(monkeypatch, _ledger(c1_members=7))
        assert "members-line" in _kinds(drift)

    def test_a_class_cell_disagreeing_with_its_section_is_reported(self, monkeypatch):
        drift = _regions(monkeypatch, _ledger(c1_cell="9"))
        assert "class-index-count" in _kinds(drift)

    def test_a_bare_cell_hiding_struck_rows_is_reported(self, monkeypatch):
        """THE §C3 SHAPE -- the gap that let a wholly-closed class read as live.

        A cell that declares no ``(N live, M closed)`` split was skipped outright
        by the pre-existing contract, so every member could be struck and the
        class still advertised as open work.
        """
        text = _ledger(
            c1_cell="2",
            c1_rows=("| ~~`DEF-1`~~ | site | closed | major |",
                     "| ~~`DEF-2`~~ | site | closed | minor |"),
            appendix=("| ~~`DEF-1`~~ | §C1 | site |",
                      "| ~~`DEF-2`~~ | §C1 | site |"),
            headline=0,
        )
        drift = _regions(monkeypatch, text)
        assert "class-index-live-split" in _kinds(drift)
        assert any("0 live, 2 closed" in d["detail"] for d in drift)

    def test_a_declared_live_split_that_is_wrong_is_reported(self, monkeypatch):
        text = _ledger(
            c1_cell="2 (**2 live**, 0 closed)",
            c1_rows=("| ~~`DEF-1`~~ | site | closed | major |",
                     "| `DEF-2` | site | open | minor |"),
            appendix=("| ~~`DEF-1`~~ | §C1 | site |", "| `DEF-2` | §C1 | site |"),
            headline=1,
        )
        drift = _regions(monkeypatch, text)
        assert "class-index-live-split" in _kinds(drift)

    def test_appendix_b_unstruck_for_a_struck_row_is_reported(self, monkeypatch):
        """Appendix B's own header claims it "cannot drift" from the member rows.
        Twelve ids had, because nothing compared the two strike markers."""
        text = _ledger(
            c1_cell="2 (**1 live**, 1 closed)",
            c1_rows=("| ~~`DEF-1`~~ | site | closed | major |",
                     "| `DEF-2` | site | open | minor |"),
            appendix=("| `DEF-1` | §C1 | site |", "| `DEF-2` | §C1 | site |"),
            headline=1,
        )
        drift = _regions(monkeypatch, text)
        assert "appendix-b-strike" in _kinds(drift)
        assert any("DEF-1" in d["detail"] for d in drift)

    def test_a_probe_aimed_at_a_struck_row_is_reported(self, monkeypatch):
        """The asymmetry that made 10 of 11 strike candidates noise: the suite
        required every LIVE row to carry a probe and never required a STRUCK row
        to lose one."""
        text = _ledger(
            c1_cell="2 (**1 live**, 1 closed)",
            c1_rows=("| ~~`DEF-1`~~ | site | closed | major |",
                     "| `DEF-2` | site | open | minor |"),
            appendix=("| ~~`DEF-1`~~ | §C1 | site |", "| `DEF-2` | §C1 | site |"),
            headline=1,
        )
        monkeypatch.setattr(gen, "_probe_ids", lambda: {"DEF-1", "DEF-2"})
        drift = gen.find_drift(text)
        assert "probe-roster" in _kinds(drift)
        assert any("DEF-1" in d["detail"] for d in drift)
        assert not any("DEF-2" in d["detail"] and d["region"] == "probe-roster"
                       for d in drift), "a LIVE row keeping its probe is correct"


class TestTheTablesAreDerived:
    """The §2 population and audience tables and the headline split were
    hand-typed until 2026-09-08; the audience figure sat at 62 through 63
    closures. Each region fires for its own reason, and the closed-world arm
    names a row nobody counted instead of dropping it."""

    def test_a_mixed_class_converges_when_its_rows_carry_their_tags(self, monkeypatch):
        text = _ledger(mixed=True, headline=3, split=(2, 1, 0),
                       aud_table={"ADOPTER": 2, "MAINTAINER": 1, "OPERATOR": 0})
        assert _regions(monkeypatch, text) == []

    def test_a_stale_headline_split_is_reported(self, monkeypatch):
        drift = _regions(monkeypatch, _ledger(split=(9, 0, 0),
                                              pop_table={"LOGIC_BUG": 2, "HYGIENE": 0, "OPERATOR_ACTION": 0}))
        assert _kinds(drift) == {"headline-split"}
        assert any("(9, 0, 0)" in d["detail"] and "(2, 0, 0)" in d["detail"] for d in drift)

    def test_a_stale_adopter_figure_is_reported(self, monkeypatch):
        drift = _regions(monkeypatch, _ledger(adopter=9,
                                              aud_table={"ADOPTER": 2, "MAINTAINER": 0, "OPERATOR": 0}))
        assert _kinds(drift) == {"headline-adopter"}

    def test_a_stale_population_table_is_reported(self, monkeypatch):
        drift = _regions(monkeypatch, _ledger(pop_table={"LOGIC_BUG": 9, "HYGIENE": 0, "OPERATOR_ACTION": 0}))
        assert _kinds(drift) == {"population-table"}
        assert any("LOGIC_BUG = 9" in d["detail"] for d in drift)

    def test_a_stale_audience_table_is_reported(self, monkeypatch):
        drift = _regions(monkeypatch, _ledger(aud_table={"ADOPTER": 9, "MAINTAINER": 0, "OPERATOR": 0}))
        assert _kinds(drift) == {"audience-table"}

    def test_an_audience_row_is_keyed_on_the_whole_token(self, monkeypatch):
        """``OPERATOR`` must not match the head of ``OPERATOR_ACTION`` -- the
        audience table used to carry that label and the population table
        still does."""
        text = _ledger(aud_table={"ADOPTER": 2, "MAINTAINER": 0, "OPERATOR_ACTION": 5})
        drift = _regions(monkeypatch, text)
        assert "vocabulary" in _kinds(drift)
        assert any("no row for OPERATOR" in d["detail"] for d in drift)
        assert not any(d["region"] == "audience-table" for d in drift)

    def test_a_mixed_class_row_without_its_own_cells_is_named(self, monkeypatch):
        text = _ledger(mixed=True, headline=3, split=(2, 0, 0),
                       c2_rows=("| `DEF-3` | site | what | nit |",))
        drift = _regions(monkeypatch, text)
        assert "vocabulary" in _kinds(drift)
        assert any("DEF-3" in d["detail"] and "MIXED" in d["detail"] for d in drift)

    def test_a_token_outside_the_vocabulary_is_named(self, monkeypatch):
        text = _ledger(mixed=True, headline=3, split=(2, 1, 0),
                       aud_table={"ADOPTER": 2, "MAINTAINER": 1, "OPERATOR": 0},
                       c2_rows=("| `DEF-3` | site | what | nit | HYGIENE | ADOPTERS |",))
        drift = _regions(monkeypatch, text)
        assert any(d["region"] == "vocabulary" and "'ADOPTERS'" in d["detail"] for d in drift)

    def test_a_class_with_live_rows_and_a_placeholder_tag_is_named(self, monkeypatch):
        drift = _regions(monkeypatch, _ledger(c1_tags=("LOGIC_BUG", "—"),
                                              aud_table={"ADOPTER": 0, "MAINTAINER": 0, "OPERATOR": 0}))
        assert any(d["region"] == "vocabulary" and "§C1" in d["detail"] and "audience" in d["detail"]
                   for d in drift)

    def test_a_reworded_headline_is_reported_not_skipped(self, monkeypatch):
        """A split line the regex cannot find must not read as converged."""
        text = _ledger().replace(" logic bugs ", " logic-bugs ", 1)
        drift = _regions(monkeypatch, text)
        assert any(d["region"] == "headline-shape" and "no headline split line" in d["detail"]
                   for d in drift)
        text = _ledger().replace(" reach an adopter", " are adopter-facing", 1)
        drift = _regions(monkeypatch, text)
        assert any(d["region"] == "headline-shape" and "no headline adopter line" in d["detail"]
                   for d in drift)

    def test_a_classed_row_carrying_its_own_cells_is_a_contradiction(self, monkeypatch):
        """THE ARM BOTH REVIEWERS DROVE. A row with its own tags under a class
        that declares a token is counted by the class and printed by the row;
        flipping §C0's index cell from MIXED moved the adopter figure 55 -> 80
        with every gate green."""
        text = _ledger(c1_rows=("| `DEF-1` | site | what | major | HYGIENE | MAINTAINER |",
                                "| `DEF-2` | site | what | minor |"))
        drift = _regions(monkeypatch, text)
        assert any(d["region"] == "vocabulary" and "DEF-1" in d["detail"]
                   and "not MIXED" in d["detail"] for d in drift)
        # the class's own count is unchanged: the cell is reported, never counted
        assert not any(d["region"] in {"population-table", "audience-table"} for d in drift)

    def test_a_population_table_missing_a_token_is_named(self, monkeypatch):
        """Pins the population arm of the closed-world table check; the audience
        twin was pinned and this one survived a mutation (code review)."""
        drift = _regions(monkeypatch, _ledger(pop_table={"LOGIC_BUG": 2, "OPERATOR_ACTION": 0}))
        assert any(d["region"] == "vocabulary" and "no row for HYGIENE" in d["detail"]
                   for d in drift)

    def test_the_section_2_header_derives_all_three_numbers(self, monkeypatch):
        text = _ledger().replace("in 1 classes + 0 standalone", "in 47 classes + 30 standalone")
        drift = _regions(monkeypatch, text)
        assert _kinds(drift) == {"section2-header"}
        fixed, _ = gen.apply_writable(text, drift)
        assert "(2 LIVE issues in 1 classes + 0 standalone)" in fixed

    def test_struck_rows_are_counted_apart_for_the_trend(self, monkeypatch):
        """Contract rule 5's instrument -- adopter-facing fixed vs introduced --
        needs the struck side too (reflect pass)."""
        text = _ledger(mixed=True, headline=2, split=(1, 0, 0), adopter=1,
                       c1_cell="2 (**1 live**, 1 closed)",
                       c1_rows=("| ~~`DEF-1`~~ | site | closed | major |",
                                "| `DEF-2` | site | open | minor |"),
                       appendix=("| ~~`DEF-1`~~ | §C1 | site |", "| `DEF-2` | §C1 | site |"),
                       aud_table={"ADOPTER": 1, "MAINTAINER": 1, "OPERATOR": 0},
                       c2_rows=("| ~~`DEF-3`~~ | site | closed | nit | HYGIENE | MAINTAINER |",
                                "| `DEF-4` | site | what | nit | HYGIENE | MAINTAINER |"))
        d = gen.derive(text)
        assert d["population_struck"] == {"LOGIC_BUG": 1, "HYGIENE": 1, "OPERATOR_ACTION": 0}
        assert d["audience_struck"] == {"ADOPTER": 1, "MAINTAINER": 1, "OPERATOR": 0}

    def test_a_second_id_in_the_id_cell_does_not_hide_a_live_row(self, monkeypatch):
        """TP-452 1-D. Eight live rows carry a second id in their first cell
        (`DEF-536` `LG-1` ...). `live_member_ids` demanded a lone id before the
        pipe, so it returned 142 against `derive()`'s 150 -- the eight were
        invisible to the probe gate and to the Appendix B strike parity, which
        read them as "not live" and stayed silent on an index row struck over a
        live member. Both read the FIRST id now, as `struck_member_ids` always did."""
        text = _ledger(c1_rows=("| `DEF-1` `LG-1` | site | what | major |",
                                "| `DEF-2` | site | what | minor |"),
                       appendix=("| ~~`DEF-1`~~ | §C1 | site |", "| `DEF-2` | §C1 | site |"))
        assert gen.live_member_ids(text) == {"DEF-1", "DEF-2"}
        assert gen.derive(text)["live_total"] == 2
        parity = [d for d in _regions(monkeypatch, text) if d["region"] == "appendix-b-strike"]
        assert parity and "DEF-1" in parity[0]["detail"], parity

    def test_cell_ids_reads_every_id_of_the_first_cell_and_only_that_cell(self):
        """DEF-863. A row is COUNTED once, by its first id (`live_member_ids`),
        but it is ADDRESSED by any id its cell carries: the verbs and the probe
        checker look a row up by id, and until 2026-09-20 each demanded a lone
        id before the pipe, so a two-id row was invisible to strike, repin,
        file --after and the staleness axis by EITHER id. One reader, here in
        the grammar's home; the first cell ends at the first unescaped pipe, so
        an id quoted in the text cell is never read as an address."""
        assert gen.cell_ids("| `DEF-1` `LG-9` | site | what | major |") == ["DEF-1", "LG-9"]
        assert gen.cell_ids("| ~~`DEF-1`~~ ~~`LG-9`~~ | site | closed | major |") == ["DEF-1", "LG-9"]
        assert gen.cell_ids("| `DEF-371a` `DEF-371b` `DEF-371c` | site | what | minor |") == [
            "DEF-371a", "DEF-371b", "DEF-371c"]
        assert gen.cell_ids("| `DEF-2` | site | what, unlike `LG-9` | minor |") == ["DEF-2"]
        assert gen.cell_ids("| `DEF-2` | §C1 | site |") == ["DEF-2"]
        assert gen.cell_ids("| id | site | what | sev |") == []
        assert gen.cell_ids("prose naming `DEF-1`") == []
        # a backticked path or word in the cell (the Appendix A crosswalks: 38
        # such tokens on 2026-09-20) is not an id; `strike` rebuilds the cell
        # from this list, so a non-id here would be written back struck
        assert gen.cell_ids("| `DEF-583` `cc/GOAL.md` `open` | site | what | nit |") == ["DEF-583"]
        assert gen.cell_ids('| `("` `\'` | site | what | nit |') == []

    def test_a_half_struck_cell_is_named_and_a_uniform_one_is_not(self):
        """Strike state is read at row level; a cell struck on some ids only is
        a shape no writer produces (0 rows on 2026-09-20) and every verb refuses."""
        assert gen.half_struck("| `DEF-3` ~~`DEF-4`~~ | site | what | major |")
        assert gen.half_struck("| ~~`DEF-3`~~ `DEF-4` | site | what | major |")
        assert not gen.half_struck("| ~~`DEF-3`~~ ~~`DEF-4`~~ | site | closed | major |")
        assert not gen.half_struck("| `DEF-3` `DEF-4` | site | what | major |")
        assert not gen.half_struck("| `DEF-3` | site | what ~~struck words~~ | major |")
        assert not gen.half_struck("| id | site | what | sev |")

    def test_a_co_ids_index_row_and_probe_are_held_to_the_row_it_shares(self, monkeypatch):
        """Both reviews of DEF-863: regions 5 and 6 keyed on FIRST ids, so a
        co-id's index row struck over a live member (`LG-1` here) and a co-id's
        probe left on a struck row were reported by nothing -- and the checker's
        retired filter, reading the whole cell now, no longer surfaces the
        second as a strike candidate either. Membership is per id."""
        live = _ledger(c1_rows=("| `DEF-1` `LG-1` | site | what | major |",
                                "| `DEF-2` | site | what | minor |"),
                       appendix=("| `DEF-1` | §C1 | site |", "| ~~`LG-1`~~ | §C1 | site |",
                                 "| `DEF-2` | §C1 | site |"))
        parity = [d for d in _regions(monkeypatch, live) if d["region"] == "appendix-b-strike"]
        assert parity and "LG-1" in parity[0]["detail"] and "live in its class section" in parity[0]["detail"]
        struck = _ledger(
            c1_cell="2 (**1 live**, 1 closed)",
            c1_rows=("| ~~`DEF-1`~~ ~~`LG-1`~~ | site | closed | major |",
                     "| `DEF-2` | site | open | minor |"),
            appendix=("| ~~`DEF-1`~~ | §C1 | site |", "| ~~`LG-1`~~ | §C1 | site |",
                      "| `DEF-2` | §C1 | site |"),
            headline=1, split=(1, 0, 0), adopter=1,
        )
        monkeypatch.setattr(gen, "_probe_ids", lambda: {"LG-1", "DEF-2"})
        roster = [d for d in gen.find_drift(struck) if d["region"] == "probe-roster"]
        assert [d["detail"].split(":")[0] for d in roster] == ["LG-1"]
        # and a struck co-id's index row left unstruck is the other direction
        half = struck.replace("| ~~`LG-1`~~ | §C1 | site |", "| `LG-1` | §C1 | site |")
        parity = [d for d in _regions(monkeypatch, half) if d["region"] == "appendix-b-strike"]
        assert parity and "LG-1" in parity[0]["detail"] and "unstruck in Appendix B" in parity[0]["detail"]

    def test_a_maintainer_row_naming_an_adopter_victim_is_an_advisory_not_drift(self, monkeypatch):
        text = _ledger(mixed=True, headline=3, split=(2, 1, 0),
                       aud_table={"ADOPTER": 2, "MAINTAINER": 1, "OPERATOR": 0},
                       c2_rows=("| `DEF-3` | site | broken. **Named user:** an adopter whose init fails. | nit | HYGIENE | MAINTAINER |",))
        assert _regions(monkeypatch, text) == []
        d = gen.derive(text)
        assert len(d["tag_advisories"]) == 1 and "DEF-3" in d["tag_advisories"][0]

    def test_the_two_vocabularies_are_disjoint(self):
        """`_POPULATION_TABLE_ROW` is tried before `_AUDIENCE_TABLE_ROW` in the
        same window, so the two are told apart by spelling alone (failure-mode
        pass). A token in both would let one table swallow the other's row."""
        assert set(gen.POPULATIONS).isdisjoint(gen.AUDIENCES)
        assert gen.MIXED not in gen.POPULATIONS + gen.AUDIENCES

    def test_a_closed_class_may_keep_its_placeholder(self, monkeypatch):
        """§C47 is the retained-so-citations-resolve class: every row struck,
        tags ``—``. No live row, no count, no complaint."""
        text = _ledger(c1_tags=("—", "—"), c1_cell="2 (**0 live**, 2 closed)", headline=0,
                       c1_rows=("| ~~`DEF-1`~~ | site | closed | major |",
                                "| ~~`DEF-2`~~ | site | closed | minor |"),
                       appendix=("| ~~`DEF-1`~~ | §C1 | site |", "| ~~`DEF-2`~~ | §C1 | site |"),
                       split=(0, 0, 0), adopter=0)
        assert _regions(monkeypatch, text) == []

    def test_write_repairs_the_numbers_and_never_the_vocabulary(self, monkeypatch):
        text = _ledger(mixed=True, headline=3, split=(7, 7, 7), adopter=7,
                       pop_table={"LOGIC_BUG": 7, "HYGIENE": 7, "OPERATOR_ACTION": 7},
                       aud_table={"ADOPTER": 7, "MAINTAINER": 7, "OPERATOR": 7},
                       c2_rows=("| `DEF-3` | site | what | nit | HYGIENE | MAINTAINER |",
                                "| `DEF-4` | site | what | nit | HYGIENE | ADOPTERS |"),
                       )
        drift = _regions(monkeypatch, text)
        fixed, applied = gen.apply_writable(text, drift)
        assert applied >= 8
        # DEF-4's population is valid and counted; only its audience is the problem
        assert "**Live: 4**" in fixed and "2 logic bugs · 2 hygiene · 0 operator actions" in fixed
        assert "**2** reach an adopter" in fixed
        assert "| HYGIENE | 2 |" in fixed and "| MAINTAINER | 1 |" in fixed
        remaining = _regions(monkeypatch, fixed)
        assert _kinds(remaining) == {"vocabulary"}, remaining
        assert any("'ADOPTERS'" in d["detail"] for d in remaining)


    def test_a_class_mixed_on_one_axis_is_a_class_not_a_standalone(self):
        """`derive` splits `classes_with_live` from `standalone_live` on the
        BOTH-axes test (the `(MIXED, MIXED)` line) deliberately: a class MIXED
        on one axis still has a shared unit of work, so it is a class. Pinned
        because the row tool's sibling rule went per-axis on 2026-09-20 and a
        class-fix sweep would find that line next -- widening it to either
        axis moved the live header 33 classes / 41 standalone to 29 / 46 with
        every synthetic case green (failure-mode pass). Earn-the-red: widen the
        line to `MIXED in (cpop, caud)` and this reds on the split."""
        text = _ledger(
            c1_tags=("LOGIC_BUG", "MIXED"),
            c1_rows=("| `DEF-1` | site | what | major | LOGIC_BUG | ADOPTER |",
                     "| `DEF-2` | site | what | minor | LOGIC_BUG | MAINTAINER |"),
            split=(2, 0, 0), adopter=1,
            aud_table={"ADOPTER": 1, "MAINTAINER": 1, "OPERATOR": 0},
        )
        d = gen.derive(text)
        assert (d["classes_with_live"], d["standalone_live"]) == (1, 0)
        assert d["audience_live"] == {"ADOPTER": 1, "MAINTAINER": 1, "OPERATOR": 0}
        assert d["population_live"]["LOGIC_BUG"] == 2 and d["tag_problems"] == []


class TestRepair:
    def test_write_repairs_the_literal_substitution_regions(self, monkeypatch):
        text = _ledger(headline=99, c1_members=7)
        drift = _regions(monkeypatch, text)
        fixed, applied = gen.apply_writable(text, drift)
        assert applied == 2
        assert "**Live: 2**" in fixed
        assert "**Members (2)**" in fixed
        assert _regions(monkeypatch, fixed) == []

    def test_write_leaves_the_judgement_regions_alone(self, monkeypatch):
        """A generator that guessed at which row to STRIKE or which probe to
        retire would be inventing content, not deriving it.

        ⚠ The class-index cells used to be in this set and were MOVED OUT on
        2026-09-02. That was a mis-classification: a member count and a live
        split are pure derivations of the member rows -- only the strike marker
        and the probe roster encode a judgement about whether work is DONE.
        Filing 40 rows made the cost visible, because 16 cells then needed
        hand-editing that the tool could compute exactly."""
        text = _ledger(
            c1_cell="2",
            c1_rows=("| ~~`DEF-1`~~ | site | closed | major |",
                     "| ~~`DEF-2`~~ | site | closed | minor |"),
            appendix=("| `DEF-1` | §C1 | site |", "| `DEF-2` | §C1 | site |"),
            headline=0,
        )
        drift = _regions(monkeypatch, text)
        fixed, _ = gen.apply_writable(text, drift)
        remaining = _kinds(_regions(monkeypatch, fixed))
        assert "appendix-b-strike" in remaining, (
            "a strike marker records a human decision that work is closed; the "
            "generator must never invent one"
        )
        assert "class-index-live-split" not in remaining, (
            "class-index cells are pure derivations and ARE written -- see the "
            "docstring; if this fails the writable set has regressed"
        )


class TestItFailsClosed:
    def test_a_ledger_it_cannot_parse_is_not_an_honest_null(self, tmp_path, monkeypatch, capsys):
        """A broken matcher must never report 'no drift' over a file nobody parsed."""
        stub = tmp_path / "FORWARD_LEDGER.md"
        stub.write_text("# not a ledger\n", encoding="utf-8")
        monkeypatch.setattr(gen, "_LEDGER", stub)
        assert gen.main(["--check"]) == 1
        assert "vacuously" in capsys.readouterr().err

    def test_a_latin1_ledger_is_refused_loudly_not_a_traceback(self, tmp_path, monkeypatch, capsys):
        """Ledger DEF-829: ``UnicodeDecodeError`` is a ``ValueError`` the
        ``except OSError`` let past. The unreadable limb already fails closed
        and loud; a code-page re-save now takes it too."""
        stub = tmp_path / "FORWARD_LEDGER.md"
        stub.write_bytes(b"# ledger\n\n| `DEF-1` | caf\xe9 |\n")
        monkeypatch.setattr(gen, "_LEDGER", stub)
        assert gen.main(["--check"]) == 1
        assert "cannot read" in capsys.readouterr().err

    def test_a_latin1_probe_file_yields_no_ids_not_a_traceback(self, tmp_path, monkeypatch):
        """The sibling JSON reader in the same script, same rule."""
        bad = tmp_path / "LEDGER_PROBES.json"
        bad.write_bytes(b'{"probes": [{"id": "DEF-1", "note": "caf\xe9"}]}')
        monkeypatch.setattr(gen, "_PROBES", bad)
        assert gen._probe_ids() == set()

    def test_an_absent_ledger_is_a_quiet_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gen, "_LEDGER", tmp_path / "nope.md")
        assert gen.main([]) == 0

    def test_check_and_write_are_mutually_exclusive(self):
        assert gen.main(["--check", "--write"]) == 2

    def test_write_exits_nonzero_while_a_judgement_region_remains(self, tmp_path, monkeypatch, capsys):
        """`--write; echo $?` read 0 while MANUAL lines scrolled past (failure-mode pass)."""
        stub = tmp_path / "FORWARD_LEDGER.md"
        stub.write_text(_ledger(mixed=True, headline=9, split=(2, 1, 0),
                                aud_table={"ADOPTER": 2, "MAINTAINER": 1, "OPERATOR": 0},
                                c2_rows=("| `DEF-3` | site | what | nit |",)), encoding="utf-8")
        monkeypatch.setattr(gen, "_LEDGER", stub)
        monkeypatch.setattr(gen, "_probe_ids", lambda: set())
        monkeypatch.setattr(gen, "_FLOOR_SECTIONS", 1)
        monkeypatch.setattr(gen, "_FLOOR_ROWS", 1)
        assert gen.main(["--write"]) == 1
        out = capsys.readouterr().out
        assert "literal repair" in out and "MANUAL  [vocabulary]" in out
        assert "**Live: 3**" in stub.read_text(encoding="utf-8")


class TestTheLiveLedgerConverges:
    """THE GATE. Everything above proves the rules fire; this is what makes the
    generator load-bearing rather than optional."""

    def test_every_derived_region_matches_the_member_rows(self):
        if not gen._LEDGER.is_file():
            pytest.skip("FORWARD_LEDGER.md is self-host only")
        drift = gen.find_drift(gen._LEDGER.read_text(encoding="utf-8"))
        assert not drift, (
            f"{len(drift)} ledger region(s) disagree with the member rows:\n"
            + "\n".join(f"  [{d['region']}] {d['detail']}" for d in drift)
            + "\n\nRun `python3 scripts/generate_ledger_regions.py --write` for the "
            "literal repairs; the class-index, Appendix B and probe-roster entries "
            "name a judgement call and must be made by hand. Do NOT relax this "
            "assertion -- an unstated count is not an accurate one."
        )

    def test_the_json_mode_reports_the_same_population(self, capsys):
        if not gen._LEDGER.is_file():
            pytest.skip("FORWARD_LEDGER.md is self-host only")
        gen.main(["--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["derived"]["live_total"] >= gen._FLOOR_ROWS, (
            "the live-row floor collapsed; the parser has broken and every "
            "assertion here would pass vacuously"
        )


class TestTheFloorsAreDerivedFromTheRecord:
    """TP-452 1-D. The row floors are parser-collapse guards, not targets: a
    floor that sits within reach of the live count reds on honest work (the
    ADOPTER floor crossed three times in 2026-09 and was moved by hand each
    time), and the 2026-09-20 rebuild left exactly 150 member rows under a
    floor of 150. So every floor is HALF of a dated figure `derive()` read from
    the pre-rebuild record file, and nothing else in the tree restates it."""

    _RECORD = REPO_ROOT / "task-packs" / "FORWARD_LEDGER_PRE_REBUILD_2026-09-20.md"

    def test_every_floor_is_at_most_half_its_snapshot_figure(self):
        snap = gen._SNAPSHOT_2026_09_20
        assert gen._FLOOR_ROWS * 2 <= snap["live"], (
            "the row floor was raised toward the live count -- it is a collapse "
            "guard, derived as half the dated snapshot, never a target"
        )
        # The section floor too (both reviewers, 2026-09-20): it was the one
        # hand literal left, and the cut had just moved 53 sections to 33.
        assert gen._FLOOR_SECTIONS * 2 <= snap["sections"], (
            "the section floor was raised toward the live count"
        )
        for tag, floor in (gen._FLOOR_POPULATION, gen._FLOOR_AUDIENCE):
            assert floor * 2 <= snap[tag], f"the {tag} floor was raised toward its live count"
        assert gen._FLOOR_POPULATION[0] in gen.POPULATIONS
        assert gen._FLOOR_AUDIENCE[0] in gen.AUDIENCES

    def test_the_snapshot_matches_its_tracked_fixture(self):
        """The record file lives on one disk (untracked, on the record branch), so
        the arm below skips on every clone and CI job -- and a rebuild that
        forgets to move the dict would red nowhere but here (the failure-mode
        lane, 2026-09-21). The four figures were written ONCE from `derive()`
        over the record file (driven equal on 2026-09-21) into a tracked
        fixture, so the dict is pinned everywhere; the live-record arm stays as
        the stronger check where the file is present."""
        fixture = REPO_ROOT / "tests" / "fixtures" / "ledger_snapshot_2026_09_20.json"
        assert gen._SNAPSHOT_2026_09_20 == json.loads(fixture.read_text(encoding="utf-8")), (
            "the snapshot dict and its tracked fixture disagree -- a rebuild moved one "
            "without the other; re-derive both from the record file, never by hand"
        )

    def test_the_snapshot_is_what_derive_reads_from_the_record_file(self):
        if not self._RECORD.is_file():
            pytest.skip("the 2026-09-20 pre-rebuild record is self-host only (record branch)")
        d = gen.derive(self._RECORD.read_text(encoding="utf-8"))
        snap = gen._SNAPSHOT_2026_09_20
        assert (d["live_total"], d["class_count"], d["population_live"]["HYGIENE"], d["audience_live"]["MAINTAINER"]) \
            == (snap["live"], snap["sections"], snap["HYGIENE"], snap["MAINTAINER"]), (
            "the snapshot dict no longer matches what derive() reads from the record "
            "file -- the dict was edited by hand, or the record was; the record is "
            "never edited (Core Rule 13), so re-derive the dict"
        )


class TestClassIndexAnchorGrammar:
    """The class-index row's anchor is the heading's rendered slug since
    2026-09-21 (the bare `#c14` form resolved to no heading once the ledger
    shipped and tests/test_md_heading_anchors.py read it); the grammar accepts
    both spellings so an older snapshot still parses, and nothing else."""

    @pytest.mark.parametrize("row", [
        "| [§C14](#c14) | Make two gates key on the event | 2 | LOGIC_BUG | ADOPTER | — |",
        "| [§C14](#c14--make-two-gates-key-on-the-event) | Make two gates | 2 | LOGIC_BUG | ADOPTER | — |",
        "| [§C0](#c0-standalone-no-shared-unit-of-work) | Standalone | 74 | MIXED | MIXED | — |",
    ])
    def test_both_anchor_spellings_are_class_index_rows(self, row):
        m = gen._CLASS_TABLE_ROW.match(row)
        assert m and m.group(1) in {"§C14", "§C0"}, row

    @pytest.mark.parametrize("row", [
        "| [§C14](#x14) | not a class anchor | 2 | LOGIC_BUG | ADOPTER | — |",
        "| [§C14](#c14 extra) | a space breaks the slug | 2 | LOGIC_BUG | ADOPTER | — |",
        "| `DEF-1` | a member row | text | minor |",
    ])
    def test_other_shapes_are_not_class_index_rows(self, row):
        assert gen._CLASS_TABLE_ROW.match(row) is None, row

    def test_every_live_index_anchor_is_a_heading_the_file_renders(self):
        # The live file, when present: each `[§CN](#anchor)` must name an anchor
        # that the file's own `### §CN` heading yields (the same slugger
        # tests/test_md_heading_anchors.py trusts), so the table of contents
        # cannot silently point at nothing again.
        from _md_anchors import heading_anchors
        ledger = REPO_ROOT / "task-packs" / "FORWARD_LEDGER.md"
        if not ledger.is_file():
            pytest.skip("self-host only: the forward ledger is absent off the dev tree")
        text = ledger.read_text(encoding="utf-8")
        available = heading_anchors(text)
        rows = [ln for ln in text.splitlines() if gen._CLASS_TABLE_ROW.match(ln)]
        assert len(rows) >= gen._FLOOR_SECTIONS, "the class index shrank below the section floor"
        dangling = []
        misnamed = []
        for ln in rows:
            label = ln.split("](#", 1)[0].rsplit("[", 1)[1]          # "§C14"
            anchor = ln.split("](#", 1)[1].split(")", 1)[0]          # "c14--make-..."
            if anchor.lower() not in available:
                dangling.append(anchor)
            # The anchor must name ITS OWN heading, not merely some heading: a
            # swapped anchor resolves and still misroutes (the code-review lane
            # drove the swap green against the resolve-only check).
            own = label.lower().replace("§", "")
            if not (anchor.lower() == own or anchor.lower().startswith(own + "-")):
                misnamed.append(f"{label} -> #{anchor}")
        assert not dangling, f"class-index anchors that no heading renders: {dangling}"
        assert not misnamed, f"class-index anchors that name another class's heading: {misnamed}"
