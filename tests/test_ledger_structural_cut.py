# pytest-marker: default-unit
"""Contract for ``scripts/ledger_structural_cut.py`` -- TP-452 1-D's cut.

The cut is the pass that turns the rebuilt ledger into the file that ships:
every struck row and every history block leaves, the mechanism block moves
under the contract, and what left is written to a record payload. A cut that
silently dropped a live row, or kept one struck row, would be a wrong ledger
with every gate green -- the live floors sit at half the snapshot precisely
so they cannot notice a handful of rows. So every rule here is driven on a
synthetic ledger in the SAME grammar the real file uses (the generator's own
regexes are the oracle), each refusal on a fixture that violates exactly it,
and every expectation is computed from the fixture's row lists, never typed.
The live ledger is not read: the cut is proven on a tree it was not written
on, and 1-D's run over the rebuilt file has its own verification.

Both review lanes of 2026-09-20 added rows here: the file-wide live-id proof
(two thirds of the ledger's live ids sit outside the class sections, which
``derive()`` never reads), the ``--strike-id`` flag that makes the shipped
cut reproducible from its flags, the crosswalk exemption, the ``§4A``-homed
Appendix B row, the false double-take on a struck row inside a dropped block,
the tilde fence, the pointer report and the honest dry-run.

Loaded via ``importlib.spec_from_file_location`` per ``tests/CLAUDE.md`` --
``scripts/`` is not an importable package; the module is registered in
``sys.modules`` before ``exec_module`` so its dataclasses resolve on 3.14.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = REPO_ROOT / "scripts" / "ledger_structural_cut.py"

if not _SCRIPT.is_file():  # pragma: no cover - adopter tree
    pytest.skip("scripts/ledger_structural_cut.py is self-host dev tooling",
                allow_module_level=True)


def _load():
    spec = importlib.util.spec_from_file_location("ledger_structural_cut", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


cutmod = _load()
gen = cutmod._GEN
DATE = "2026-09-20"
NOTE = ("_The single forward-work tracker. **Rebuilt 2026-09-20** to forward work only; the\n"
        "pre-rebuild file is `task-packs/FORWARD_LEDGER_PRE_REBUILD_2026-09-20.md` on the record branch._")
PROBED = {"DEF-1", "DEF-3", "DEF-4"}


# --------------------------------------------------------------------------
# The synthetic ledger: every shape the real file has and the cut must handle.
# Each knob adds exactly one shape a rule below is driven on.
# --------------------------------------------------------------------------
def _ledger(*, stray_h2: bool = False, paragraph_abuts_table: bool = False, struck_a3_row: bool = False,
            b_row_4a: bool = False, struck_in_s7: bool = False, tilde_fence: bool = False,
            no_header_note: bool = False) -> str:
    stray = "## Stray note nobody decided about\n\nsome text\n\n" if stray_h2 else ""
    header_note = "" if no_header_note else (
        "_The single forward-work tracker. **Rebuilt 2026-08-20** on a full census: every live row\n"
        "re-verified at HEAD._\n\n")
    fence = "~~~bash" if tilde_fence else "```bash"
    fence_end = "~~~" if tilde_fence else "```"
    s1b_table = ("| # | id | what |\n|---|---|---|\n"
                 "| 1 | `DEF-537` `DEC-25` | seed the repo (see the `DEC-25` note above) |\n")
    s1b = (("⚠ **Two consequences are live NOW.** the consequence.\n" + s1b_table +
            "\n⚠ **`DEC-31`, 2026-09-07 — the seed is unchanged.** this one stays.\n")
           if paragraph_abuts_table else
           ("⚠ **Two consequences are live NOW.** the consequence.\n\n"
            "⚠ **`DEC-31`, 2026-09-07 — the seed is unchanged.** this one stays.\n\n" + s1b_table))
    a3_extra = "| ~~`DEF-999`~~ | struck twice; the crosswalk sentence a citation lands on |\n" if struck_a3_row else ""
    b_extra = "| ~~`DEC-28`~~ | §4A | site |\n" if b_row_4a else ""
    s7_extra = "| ~~`DEF-99`~~ | FIXED | also dead |\n" if struck_in_s7 else ""
    return f"""# Forward Ledger

{header_note}**Live: 3** — 2 logic bugs · 1 hygiene · 0 operator actions.
**2** reach an adopter. Counted apart on purpose.

---

## ▶ START HERE — Session note 2026-08-26

history one

## ⚠ Session note 2026-08-20

history two, with a fence:

```bash
# a shell comment that is not a heading
echo hi
```

{stray}## How this file defends itself

_Three mechanisms._

**1. Derived regions.** counts are generated.

{fence}
# inside a fence: still not a heading after the move
python3 scripts/generate_ledger_regions.py --check
{fence_end}

⚠ **From the 2026-08-20 rebuild until 2026-09-02 this paragraph was ASPIRATIONAL** and
it stayed so for a while.

**2. Probes.** every row can re-derive its own claim.

## The contract — what belongs in this file

- rule one

Struck rows are in §7 with that evidence.

**Editing rules.** by content anchor.

## How to read a status tag

| Tag | Meaning |
|---|---|
| `open` | the default |

## §1 — Launch gates (2 day-one defects)

### §1A — day one

| # | id | issue | site | root cause |
|---|---|---|---|---|
| 1 | ~~`DEF-426`~~ `TP-421` | closed, but the pack id is live | `x.py` | §C1 |
| 2 | ~~`DEF-429`~~ | ✅ closed | `y.py` | §C1 |
| 3 ○ | `LG-14` | open | `z.md` | — |
| 4 | ~~`DEF-425`~~ ~~`DEF-455`~~ | ✅ closed, both | `w.py` | §C1 |
| 5 | ~~`DEF-445`~~ ✅ **CLOSED (`67f5bb4`)** — bled into the id cell | `v.py` is the site | §C1 |

### §1B — the operator sequence

⚠ **`DEC-25`, 2026-08-20 — step 2 changes shape.** essay line one
essay line two.

{s1b}
## §2 - Open fixes, by unit of work (3 LIVE issues in 1 classes + 1 standalone)

| population | live | what it means |
|---|---|---|
| LOGIC_BUG | 2 | meaning |
| HYGIENE | 1 | meaning |
| OPERATOR_ACTION | 0 | meaning |

| audience | live |
|---|---|
| **ADOPTER** — someone who ran `pip install espalier` | **2** |
| MAINTAINER | 1 |
| OPERATOR | 0 |

### Class index

| § | class | members | population | audience | effort |
|---|---|---|---|---|---|
| [§C1](#c1) | A class | 3 (**2 live**, 1 closed) | LOGIC_BUG | ADOPTER | ~1 LOC |
| [§C2](#c2) | Standalone | 2 (**1 live**, 1 closed) | MIXED | MIXED | — |
| [§C47](#c47) | Closed — retained so citations resolve | 1 (**0 live**, 1 closed) | LOGIC_BUG | ADOPTER | — |

### §C1 - A class

**Members (3)** - derived, never typed

| id | site | what | sev |
|---|---|---|---|
| `DEF-1` `LG-1` | site | what | major |
| ~~`DEF-2`~~ | site | ✅ closed | minor |
| `DEF-3` | site | what | minor |

### §C2 - Standalone

**Members (2)** - derived, never typed

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|
| `DEF-4` | site | what | nit | HYGIENE | MAINTAINER |
| ~~`DEF-5`~~ | site | closed | nit | HYGIENE | MAINTAINER |

### §C47 — Closed — retained so citations resolve

**Members (1)** - derived, never typed

| id | site | what | sev |
|---|---|---|---|
| ~~`DEF-6`~~ | site | closed | nit |

## §3 — New features (2)

| id | site | what |
|---|---|---|
| `TP-356` | `Deferred/TP-356.md` | held |
| ~~`DEF-414f`~~ | `x.py` | ✅ closed |

## §7 — Struck in this rebuild (1)

| id | shape | what |
|---|---|---|
| `INV-10` | FIXED | dead |
{s7_extra}
## Appendix A3 — retired ids

| id | where it went |
|---|---|
| `PR-1` | removed as moot |
{a3_extra}
## Appendix B - id index

| id | § | site |
|---|---|---|
| `DEF-1` | §C1 | site |
| `LG-1` | §C1 | site |
| ~~`DEF-2`~~ | §C1 | site |
| `DEF-3` | §C1 | site |
| `DEF-4` | §C2 | site |
| ~~`DEF-5`~~ | §C2 | site |
| ~~`DEF-6`~~ | §C47 | site |
| ~~`DEF-426`~~ | §C1 | site |
| ~~`DEF-429`~~ | §C1 | site |
{b_extra}
## Appendix C — where the pre-rebuild detail went

_The §2 as it stood is preserved elsewhere._
"""


def _opts(**over) -> "cutmod.Options":
    base = dict(
        date=DATE,
        drop_h2=["▶ START HERE", "⚠ Session note", "§7 —", "Appendix C —"],
        move_h2_into_contract=["How this file defends itself"],
        drop_class_sections=["§C47"],
        drop_paragraphs=["⚠ **From the 2026-08-20 rebuild until 2026-09-02",
                         "⚠ **`DEC-25`, 2026-08-20",
                         "⚠ **Two consequences are live NOW"],
        rebuilt_note=NOTE,
    )
    base.update(over)
    return cutmod.Options(**base)


@pytest.fixture
def result():
    return cutmod.cut(_ledger(), PROBED, _opts())


# --------------------------------------------------------------------------
# The cut
# --------------------------------------------------------------------------
class TestTheCutDropsOnlyWhatItWasTold:
    def test_every_struck_row_leaves_and_every_live_id_stays(self, result):
        out = result.text
        assert gen.live_member_ids(out) == gen.live_member_ids(_ledger()) == {"DEF-1", "DEF-3", "DEF-4"}
        assert cutmod.classify_struck_rows(out.split("\n")) == {}
        rd = result.report["rows_dropped"]
        assert rd["class"] == ["DEF-2", "DEF-5", "DEF-6"]
        # Every id of a multi-id row is recorded, not the first (code review NIT).
        assert rd["table"] == ["DEF-429", "DEF-425", "DEF-455", "DEF-445", "DEF-414f"]
        assert rd["appendix-b"] == ["DEF-2", "DEF-5", "DEF-6", "DEF-426", "DEF-429"]
        # A row whose id cell keeps a LIVE co-id beside a struck id is not struck.
        assert "| 1 | ~~`DEF-426`~~ `TP-421` |" in out
        assert "| 1 | `DEF-537` `DEC-25` |" in out and "| 3 ○ | `LG-14` |" in out
        assert "`TP-356`" in out and "`PR-1`" in out

    def test_the_file_wide_live_id_population_is_conserved(self, result):
        """The proof that carries weight: every live id in EVERY table, not the
        class sections `derive()` reads. `INV-10` sits inside the dropped §7
        block, so it is expected to leave; everything else must come through."""
        before = cutmod.live_table_ids(_ledger().split("\n"))
        after = cutmod.live_table_ids(result.text.split("\n"))
        assert before - after == {"INV-10"} and after <= before
        assert {"TP-421", "LG-14", "DEF-537", "DEC-25", "TP-356", "PR-1", "DEF-1", "LG-1", "DEF-3", "DEF-4"} <= after
        assert "DEF-2" not in before and "DEF-426" not in before  # struck ids are not live
        assert result.report["live_table_ids"] == {"before": len(after), "after": len(after)}

    def test_a_live_id_lost_outside_the_class_sections_is_refused(self, monkeypatch):
        # The refusal path itself, driven: the second census (after the cut)
        # comes back one id short, as it would if a future edit ate a §1 row.
        real = cutmod.live_table_ids
        calls = {"n": 0}

        def short(lines, skip=None):
            calls["n"] += 1
            ids = real(lines, skip)
            return ids - {"LG-14"} if calls["n"] == 2 else ids
        monkeypatch.setattr(cutmod, "live_table_ids", short)
        with pytest.raises(cutmod.Refused, match=r"live ids outside the dropped ranges moved: lost \['LG-14'\]"):
            cutmod.cut(_ledger(), PROBED, _opts())

    def test_derive_reads_the_same_population_before_and_after(self, result):
        before, after = gen.derive(_ledger()), gen.derive(result.text)
        assert (before["live_total"], before["population_live"], before["audience_live"]) == \
            (after["live_total"], after["population_live"], after["audience_live"])
        assert result.report["live_before"] == result.report["live_after"] == 3

    def test_the_history_blocks_leave_and_the_mechanism_block_moves_under_the_contract(self, result):
        out = result.text
        assert "## ▶ START HERE" not in out and "## ⚠ Session note" not in out
        assert "## §7 —" not in out and "## Appendix C —" not in out and "`INV-10`" not in out
        contract = out.index("## The contract")
        moved = out.index("### How this file defends itself")
        status = out.index("## How to read a status tag")
        assert contract < moved < status
        # Line-anchored: `"## X" in text` is a SUBSTRING test that a demoted
        # `### X` satisfies (the ledger's own §C6 record of that trap).
        assert "## How this file defends itself" not in out.split("\n")
        assert "ASPIRATIONAL" not in out and "**2. Probes.**" in out
        # A `# comment` inside the moved block's code fence is not a heading.
        assert "# inside a fence: still not a heading after the move" in out
        assert "## inside a fence" not in out
        assert result.report["blocks_moved"] == ["How this file defends itself"]
        assert set(result.report["blocks_dropped"]) == {
            "▶ START HERE — Session note 2026-08-26", "⚠ Session note 2026-08-20",
            "§7 — Struck in this rebuild (1)", "Appendix C — where the pre-rebuild detail went"}

    def test_a_tilde_fence_in_the_moved_block_is_a_fence_too(self):
        out = cutmod.cut(_ledger(tilde_fence=True), PROBED, _opts()).text
        assert "# inside a fence: still not a heading after the move" in out
        assert "## inside a fence" not in out

    def test_the_dec25_paragraphs_leave_and_dec31_stays(self, result):
        out = result.text
        assert "`DEC-25`, 2026-08-20" not in out and "Two consequences are live NOW" not in out
        assert "`DEC-31`, 2026-09-07 — the seed is unchanged.** this one stays." in out
        assert "essay line two" not in out

    def test_an_all_struck_class_section_leaves_with_its_index_row(self, result):
        out = result.text
        assert "### §C47" not in out and "[§C47](#c47)" not in out
        assert result.report["sections_before"] == 3 and result.report["sections_after"] == 2
        assert result.report["class_sections_dropped"] == ["§C47"]

    def test_the_header_note_is_rewritten_from_the_file(self, result):
        out = result.text
        assert NOTE in out and "**Rebuilt 2026-08-20** on a full census" not in out
        why = [r["why"] for r in result.report["rewrites"]]
        assert any("record file" in w for w in why) and any("moved under the contract" in w for w in why)

    def test_the_regions_converge_after_the_cut(self, result, monkeypatch):
        monkeypatch.setattr(gen, "_probe_ids", lambda: set(PROBED))
        assert gen.find_drift(result.text) == []
        assert result.report["residual_drift"] == []
        out = result.text
        assert "| [§C1](#c1) | A class | 2 | LOGIC_BUG |" in out
        assert "| [§C2](#c2) | Standalone | 1 | MIXED |" in out
        assert "**Members (2)**" in out and "**Members (1)**" in out and "**Members (3)**" not in out

    def test_the_report_names_the_headings_whose_typed_counts_may_be_stale(self, result):
        lost = result.report["headings_that_lost_rows"]
        assert "§1A — day one" in lost and "§3 — New features (2)" in lost
        assert "Appendix B - id index" in lost and "§C1 - A class" in lost

    def test_the_report_names_every_surviving_pointer_to_what_left(self, result):
        # Failure-mode review: a dropped paragraph strands "(see the `DEC-25`
        # note above)" and a dropped block strands "Struck rows are in §7".
        pointers = result.report["pointers_to_review"]
        assert any(p["names"] == "DEC-25" and p["text"].startswith("| 1 | `DEF-537` `DEC-25` | seed the repo (see")
                   for p in pointers), pointers
        assert any(p["names"] == "§7" and p["text"].startswith("Struck rows are in §7 with that evidence")
                   for p in pointers), pointers


class TestStrikeIdMakesTheRunReproducible:
    def test_a_struck_id_leaves_with_its_row_and_is_recorded(self):
        # Code review BLOCK: the shipped cut had a hand strike on the input
        # that no flag reproduced; the flag records the edit and the row leaves.
        r = cutmod.cut(_ledger(), PROBED, _opts(strike_ids=["TP-421"]))
        assert "`TP-421`" not in r.text and "`DEF-426`" not in r.text
        assert r.report["strike_ids"] == ["TP-421"]
        assert "TP-421" in r.report["rows_dropped"]["table"] and "DEF-426" in r.report["rows_dropped"]["table"]
        assert any(w["why"] == "--strike-id TP-421 on the input" and "~~`TP-421`~~" in w["new"]
                   for w in r.report["rewrites"])
        assert "| 1 | ~~`DEF-426`~~ ~~`TP-421`~~ |" in r.payload

    def test_an_id_no_row_or_several_rows_carry_is_refused(self):
        with pytest.raises(cutmod.Refused, match="--strike-id TP-999: 0 table row"):
            cutmod.cut(_ledger(), PROBED, _opts(strike_ids=["TP-999"]))
        with pytest.raises(cutmod.Refused, match="--strike-id DEF-1: 0 table row"):
            cutmod.cut(_ledger(), PROBED, _opts(strike_ids=["DEF-1"]))  # a class-section row is not its business


class TestNothingLeavesUnrecorded:
    def test_every_line_that_left_the_file_is_in_the_payload_verbatim(self, result):
        from collections import Counter
        gone = Counter(_ledger().split("\n")) - Counter(result.text.split("\n"))
        payload = Counter(result.payload.split("\n"))
        missing = {ln: n for ln, n in gone.items() if ln.strip() and payload[ln] < n}
        assert not missing, missing

    def test_the_payload_is_labelled_a_record_and_groups_by_where(self, result):
        p = result.payload
        assert p.startswith(f"# Cut from the forward ledger on {DATE}")
        assert "RECORD SURFACE" in p
        for heading in ("## Blocks cut (4)", "## Class sections cut (1)", "## Paragraphs cut (3)",
                        "## Rows dropped, by table", "## Blocks moved under the contract (1)", "## Rewrites"):
            assert heading in p, heading
        # A backtick fence inside a dropped block cannot close the payload's tilde fence.
        assert "```bash\n# a shell comment that is not a heading\necho hi\n```" in p

    def test_the_report_counts_lines_in_and_removed(self, result):
        rep = result.report
        assert rep["lines_removed"] > 0
        assert rep["lines_in"] == len(_ledger().split("\n"))


class TestTheCrosswalksAndTheIndexAreHandledByTheirOwnRules:
    def test_a_struck_row_in_a_crosswalk_appendix_is_kept_and_reported(self):
        # Failure-mode review: A3/A4 exist so a citation does not dead-end;
        # a struck id there is a record, and dropping it would create the
        # dead end the appendix prevents.
        r = cutmod.cut(_ledger(struck_a3_row=True), PROBED, _opts())
        assert "| ~~`DEF-999`~~ | struck twice" in r.text
        assert [k["text"][:22] for k in r.report["struck_rows_kept_in_crosswalks"]] == ["| ~~`DEF-999`~~ | stru"]
        assert "DEF-999" not in r.report["rows_dropped"]["table"]

    def test_a_crosswalk_appendix_cannot_be_dropped_as_a_block(self):
        with pytest.raises(cutmod.Refused, match="the appendices are never cut"):
            cutmod.cut(_ledger(), PROBED, _opts(drop_h2=["▶ START HERE", "⚠ Session note", "§7 —",
                                                           "Appendix C —", "Appendix A3"]))

    def test_a_struck_index_row_homed_outside_a_class_section_leaves_too(self):
        # Code review WARN: `| ~~`DEC-28`~~ | §4A | site |` fails the generator's
        # `_APPENDIX_B_ROW` (a §C section only) and the first cut left it.
        r = cutmod.cut(_ledger(b_row_4a=True), PROBED, _opts())
        assert "`DEC-28`" not in r.text
        assert "DEC-28" in r.report["rows_dropped"]["appendix-b"]
        assert "| ~~`DEC-28`~~ | §4A | site |" in r.payload

    def test_a_struck_row_inside_a_dropped_block_is_not_a_double_take(self):
        # Code review WARN: the block branch took every line unconditionally,
        # so a struck row already classified refused the whole run.
        r = cutmod.cut(_ledger(struck_in_s7=True), PROBED, _opts())
        assert "`DEF-99`" not in r.text and "DEF-99" in r.report["rows_dropped"]["table"]
        assert "| ~~`DEF-99`~~ | FIXED | also dead |" in r.payload


# --------------------------------------------------------------------------
# Each refusal on a fixture that violates exactly it.
# --------------------------------------------------------------------------
class TestItRefusesRatherThanGuesses:
    def test_a_class_section_with_a_live_row_is_refused(self):
        with pytest.raises(cutmod.Refused, match="still has 2 live row"):
            cutmod.cut(_ledger(), PROBED, _opts(drop_class_sections=["§C1"]))

    def test_a_block_above_the_contract_nobody_named_is_refused(self):
        with pytest.raises(cutmod.Refused, match="sits above the contract and was neither dropped nor moved"):
            cutmod.cut(_ledger(stray_h2=True), PROBED, _opts())

    def test_a_drop_prefix_that_matches_nothing_is_refused(self):
        with pytest.raises(cutmod.Refused, match="matches no h2 heading"):
            cutmod.cut(_ledger(), PROBED, _opts(drop_h2=["▶ START HERE", "⚠ Session note", "§7 —",
                                                           "Appendix C —", "Appendix Z —"]))

    def test_a_paragraph_start_that_matches_no_paragraph_is_refused(self):
        with pytest.raises(cutmod.Refused, match="opens 0 paragraph"):
            cutmod.cut(_ledger(), PROBED, _opts(drop_paragraphs=["⚠ **Nothing opens with this"]))

    def test_a_paragraph_that_runs_into_a_table_is_refused(self):
        # Code review BLOCK: a paragraph is bounded by blank lines, so one that
        # abuts a table would take live launch-gate rows with it, unseen by
        # `derive()`. Refused by name, before the file-wide proof has to catch it.
        with pytest.raises(cutmod.Refused, match="runs into a table row at line"):
            cutmod.cut(_ledger(paragraph_abuts_table=True), PROBED, _opts())

    def test_a_missing_header_note_names_the_flag_that_asked_for_it(self):
        with pytest.raises(cutmod.Refused, match=r"--rebuilt-note \(the header note paragraph\)"):
            cutmod.cut(_ledger(no_header_note=True), PROBED, _opts())

    def test_a_move_of_a_block_that_is_not_above_the_contract_is_refused(self):
        with pytest.raises(cutmod.Refused, match="not above the contract"):
            cutmod.cut(_ledger(), PROBED, _opts(move_h2_into_contract=["How this file defends itself",
                                                                          "How to read a status tag"]))

    def test_a_struck_row_that_still_carries_a_probe_is_refused(self):
        with pytest.raises(cutmod.Refused, match=r"still carries a probe for \['DEF-2'\]"):
            cutmod.cut(_ledger(), PROBED | {"DEF-2"}, _opts())

    def test_a_missing_contract_heading_is_refused(self):
        text = _ledger().replace("## The contract — what belongs in this file", "## Something else")
        with pytest.raises(cutmod.Refused, match="exactly one `## The contract`"):
            cutmod.cut(text, PROBED, _opts())


class TestTheIdCellRule:
    @pytest.mark.parametrize("cell, struck", [
        ("~~`DEF-426`~~ `TP-421`", False),          # a live co-id beside a struck id
        ("~~`DEF-429`~~", True),
        ("~~`DEF-425`~~ ~~`DEF-455`~~", True),        # two spans
        ("~~`DEC-12` `DEF-412b`~~", True),            # one span, two ids
        ("~~`DEF-445`~~ ✅ **CLOSED (`67f5bb4`)** — bled", True),  # prose bled in; no live id-shaped token
        ("`LG-14` `LG-3`", False),
        ("`DEF-*` rows", False),                     # no id-shaped token at all
    ])
    def test_a_cell_is_struck_only_when_every_id_shaped_token_is_inside_a_span(self, cell, struck):
        assert cutmod.cell_wholly_struck(cell) is struck

    def test_the_id_cell_is_the_first_or_the_one_after_an_ordinal(self):
        assert cutmod.id_cell(["1", "~~`DEF-426`~~ `TP-421`", "issue"]) == "~~`DEF-426`~~ `TP-421`"
        assert cutmod.id_cell(["5 ○", "`LG-14`", "issue"]) == "`LG-14`"
        assert cutmod.id_cell(["`TP-356`", "site"]) == "`TP-356`"
        assert cutmod.id_cell(["[§C1](#c1)", "A class", "3"]) is None
        assert cutmod.id_cell(["**ADOPTER** — someone who ran `pip install espalier`", "**2**"]) is None
        assert cutmod.id_cell(["id", "site", "what"]) is None

    def test_live_row_ids_reads_only_the_tokens_outside_a_span(self):
        assert cutmod.live_row_ids("| 1 | ~~`DEF-426`~~ `TP-421` | x |") == ["TP-421"]
        assert cutmod.live_row_ids("| 4 | ~~`DEF-425`~~ ~~`DEF-455`~~ | x |") == []
        assert cutmod.live_row_ids("| `DEF-1` `LG-1` | site | what | major |") == ["DEF-1", "LG-1"]
        assert cutmod.live_row_ids("| LOGIC_BUG | 2 | meaning |") == []


# --------------------------------------------------------------------------
# The CLI
# --------------------------------------------------------------------------
class TestTheCli:
    def _tree(self, tmp_path: Path) -> tuple[Path, Path, Path, Path]:
        ledger = tmp_path / "FORWARD_LEDGER.rebuilt.md"
        ledger.write_text(_ledger(), encoding="utf-8")
        probes = tmp_path / "LEDGER_PROBES.rebuilt.json"
        probes.write_text(json.dumps({"_count": 3, "probes": [
            {"id": i, "cmd": "true", "open_value": "1"} for i in sorted(PROBED)]}), encoding="utf-8")
        note = tmp_path / "note.md"
        note.write_text(NOTE + "\n", encoding="utf-8")
        return ledger, probes, note, tmp_path / "out"

    def _argv(self, ledger, probes, note, out, *extra):
        return ["--ledger", str(ledger), "--probes", str(probes), "--out", str(out), "--date", DATE,
                "--drop-h2", "▶ START HERE", "--drop-h2", "⚠ Session note", "--drop-h2", "§7 —",
                "--drop-h2", "Appendix C —", "--move-h2-into-contract", "How this file defends itself",
                "--drop-paragraph", "⚠ **From the 2026-08-20 rebuild until 2026-09-02",
                "--drop-paragraph", "⚠ **`DEC-25`, 2026-08-20",
                "--drop-paragraph", "⚠ **Two consequences are live NOW",
                "--drop-class-section", "§C47", "--rebuilt-note", str(note), *extra]

    def test_it_writes_three_files_and_refuses_a_second_run(self, tmp_path, capsys):
        ledger, probes, note, out = self._tree(tmp_path)
        assert cutmod.main(self._argv(ledger, probes, note, out, "--strike-id", "TP-421")) == 0
        assert (out / "FORWARD_LEDGER.cut.md").is_file()
        assert (out / f"cut-{DATE}.md").is_file() and (out / "cut-report.json").is_file()
        assert ledger.read_text(encoding="utf-8") == _ledger(), "the input is never rewritten"
        rep = json.loads((out / "cut-report.json").read_text(encoding="utf-8"))
        assert rep["live_before"] == rep["live_after"] == 3 and rep["strike_ids"] == ["TP-421"]
        assert cutmod.main(self._argv(ledger, probes, note, out)) == 3
        assert "already holds a cut" in capsys.readouterr().err

    def test_dry_run_prints_the_report_and_writes_nothing(self, tmp_path, capsys):
        ledger, probes, note, out = self._tree(tmp_path)
        assert cutmod.main(self._argv(ledger, probes, note, out, "--dry-run", "--json")) == 0
        assert not out.exists()
        rep = json.loads(capsys.readouterr().out)
        assert rep["class_sections_dropped"] == ["§C47"]

    def test_dry_run_refuses_an_occupied_out_dir_as_the_real_run_would(self, tmp_path, capsys):
        # Failure-mode review NIT: a rehearsal that reports success where the
        # real run would refuse is a rehearsal of nothing.
        ledger, probes, note, out = self._tree(tmp_path)
        assert cutmod.main(self._argv(ledger, probes, note, out)) == 0
        assert cutmod.main(self._argv(ledger, probes, note, out, "--dry-run")) == 3
        assert "already holds a cut" in capsys.readouterr().err

    def test_a_refusal_exits_2_and_writes_nothing(self, tmp_path, capsys):
        ledger, probes, note, out = self._tree(tmp_path)
        ledger.write_text(_ledger(stray_h2=True), encoding="utf-8")
        assert cutmod.main(self._argv(ledger, probes, note, out)) == 2
        assert "REFUSED" in capsys.readouterr().err and not out.exists()

    def test_a_probes_file_whose_count_disagrees_is_refused(self, tmp_path, capsys):
        ledger, probes, note, out = self._tree(tmp_path)
        probes.write_text(json.dumps({"_count": 9, "probes": []}), encoding="utf-8")
        assert cutmod.main(self._argv(ledger, probes, note, out)) == 2
        assert "_count" in capsys.readouterr().err
