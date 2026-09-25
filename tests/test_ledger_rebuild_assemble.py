# pytest-marker: default-unit
"""Contract for ``scripts/ledger_rebuild_assemble.py`` -- the TP-452 1-B assembler.

The rebuild workflow adjudicates; this script turns the verdicts into the
rebuilt ledger. This file pins the assembler's outputs to the generator's own
grammar and to its refusals, because a rebuilt ledger that parses differently
under ``generate_ledger_regions`` -- or that silently keeps a row's old text --
is a wrong ledger with every gate green, which is the drift the whole rebuild
exists to prevent. Every test below drives it over a synthetic ledger built in
the SAME grammar the real file uses (the generator's own regexes are the
oracle), and every expectation is computed from the fixture's row lists,
never typed. The live ledger is not read here: the assembler is proven on a
tree it was not written on, and 1-D's live write has its own gate.

The fixture carries the shapes the first review found the real file has and
the first cut missed: a class MIXED on ONE axis whose rows carry six cells, a
member row whose id cell holds a second id, a numbered §1 row with two ids,
and an Appendix A3 row whose first cell is a bare id.

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
_SCRIPT = REPO_ROOT / "scripts" / "ledger_rebuild_assemble.py"

if not _SCRIPT.is_file():  # pragma: no cover - adopter tree
    pytest.skip("scripts/ledger_rebuild_assemble.py is self-host dev tooling",
                allow_module_level=True)


def _load():
    spec = importlib.util.spec_from_file_location("ledger_rebuild_assemble", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


asm = _load()
gen = asm._GEN
DATE = "2026-09-20"
EV = {"driven_command": "python3 scripts/check_ledger_probes.py --id X",
      "output_quoted": "STRIKE_CANDIDATE 1", "reason": "the probe stopped printing 1"}


# --------------------------------------------------------------------------
# The synthetic ledger.
# --------------------------------------------------------------------------
C0_ROWS = (  # MIXED on both axes: rows carry their own cells
    "| `DEF-7` | site7 | what seven | minor | HYGIENE | MAINTAINER |",
    "| `DEF-8` | site8 | what eight | nit | OPERATOR_ACTION | OPERATOR |",
)
C1_ROWS = (  # LOGIC_BUG / ADOPTER; one two-id row; one previously struck row
    "| `DEF-1` | site1 | what one | major |",
    "| `DEF-2` | site2 | what two | minor |",
    "| `DEF-3` | site3 | what three | nit |",
    "| `DEF-9` `LG-9` | site9 | what nine | minor |",
    "| ~~`DEF-4`~~ | site4 | CLOSED 2026-09-01 -- done. PRIOR TEXT: what four | minor |",
)
C2_ROWS = (  # HYGIENE / MAINTAINER
    "| `DEF-5` | site5 | what five | major |",
    "| `DEF-6` | site6 | what six | minor |",
)
C3_ROWS = (  # HYGIENE / MIXED -- MIXED on the audience axis only
    "| `DEF-11` | site11 | what eleven | minor | HYGIENE | ADOPTER |",
    "| `DEF-12` | site12 | what twelve | nit | HYGIENE | MAINTAINER |",
)
S1_ROWS = (
    "| 1 | `DEF-537` `LG-3` | the cut |",
    "| 2 | `DEF-540` | the other cut |",
    # A §1 twin: the SAME id pair as the two-id member row in §C1. The real
    # file has four (the launch gates 1, 3, 4 and 6); the workflow keys the
    # §2 row by the first id and the twin by the co-id, so a verdict on the
    # co-id with section `extra` is the twin's, never the member row's.
    "| 3 | `DEF-9` `LG-9` | the nine cut |",
)
S3_ROWS = (
    "| `TP-9` | task-packs/TP-9.md | a feature |",
    "| `TP-10` | task-packs/TP-10.md | another |",
)
A3_ROW = "| `DEC-8` | prose-only (cited but has no row) |"
SECTIONS = {"§C0": C0_ROWS, "§C1": C1_ROWS, "§C2": C2_ROWS, "§C3": C3_ROWS}


def _ids(row: str) -> list[str]:
    return asm._IDS_IN_CELL.findall(gen.member_cells(row)[0])


def _live(rows) -> int:
    return sum(1 for r in rows if not gen._is_struck(r))


def ledger(*, c2_tags: tuple[str, str] = ("HYGIENE", "MAINTAINER")) -> str:
    live = sum(_live(r) for r in SECTIONS.values())
    index = "\n".join(
        f"| {'~~' if gen._is_struck(r) else ''}`{x}`{'~~' if gen._is_struck(r) else ''} | {sec} | site |"
        for sec, rows in SECTIONS.items() for r in rows for x in _ids(r)
    )
    return f"""# Forward Ledger

**Live: {live}** — 4 logic bugs · 5 hygiene · 1 operator actions.
**5** reach an adopter. Counted apart on purpose.

## §1 - Launch gates

| # | id | what |
|---|---|---|
{chr(10).join(S1_ROWS)}

## §2 - Open fixes, by unit of work ({live} LIVE issues in 3 classes + {_live(C0_ROWS)} standalone)

| population | live | what it means |
|---|---|---|
| LOGIC_BUG | 4 | code behaves wrongly |
| HYGIENE | 5 | docs |
| OPERATOR_ACTION | 1 | no code fix exists |

| audience | live |
|---|---|
| **ADOPTER** — someone who ran `pip install espalier` | **5** |
| MAINTAINER | 4 |
| OPERATOR | 1 |

### Class index

| § | class | members | population | audience | effort |
|---|---|---|---|---|---|
| [§C0](#c0) | Standalone | {len(C0_ROWS)} | MIXED | MIXED | — |
| [§C1](#c1) | A class | {len(C1_ROWS)} (**{_live(C1_ROWS)} live**, 1 closed) | LOGIC_BUG | ADOPTER | ~1 LOC |
| [§C2](#c2) | B class | {len(C2_ROWS)} | {c2_tags[0]} | {c2_tags[1]} | ~1 LOC |
| [§C3](#c3) | C class | {len(C3_ROWS)} | HYGIENE | MIXED | ~1 LOC |

### §C0 - Standalone

**Members ({len(C0_ROWS)})** - derived, never typed

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|
{chr(10).join(C0_ROWS)}

### §C1 - A class

**Members ({len(C1_ROWS)})** - derived, never typed

| id | site | what | sev |
|---|---|---|---|
{chr(10).join(C1_ROWS)}

### §C2 - B class

**Members ({len(C2_ROWS)})** - derived, never typed

| id | site | what | sev |
|---|---|---|---|
{chr(10).join(C2_ROWS)}

### §C3 - C class

**Members ({len(C3_ROWS)})** - derived, never typed

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|
{chr(10).join(C3_ROWS)}

## §3 - New features

| id | pack | what |
|---|---|---|
{chr(10).join(S3_ROWS)}

## Appendix A3 - retired ids

| id | disposition |
|---|---|
{A3_ROW}

## Appendix A4 - re-keyed ids

| citation as written | what it meant | reads today |
|---|---|---|
| `DEF-0` (§C1) — an old cite | the old row | **`DEF-1`** |

## Appendix B - id index

| id | § | site |
|---|---|---|
{index}
"""


def probes(*ids: str) -> dict:
    return {"_README": "x", "_generated": "2026-08-20 rebuild", "_count": len(ids),
            "probes": [{"id": i, "subject": "s", "cmd": "c", "open_value": "1"} for i in ids]}


def final(**by_id) -> list[dict]:
    out = []
    for rid, d in by_id.items():
        out.append({"id": rid, "section": d.get("section", "§C1"), "verdict": d["verdict"],
                    "severity": d.get("severity"), "population": d.get("population"),
                    "audience": d.get("audience"), "fold_into": d.get("fold_into"),
                    "lane": d.get("lane", "adjudicate-0"), "probe": d.get("probe", "NOT_RUN")})
    return out


def lane(**rows) -> dict:
    return {rid: {"anchor": r.get("anchor"), "body": r.get("body"), "lane": "adjudicate-0",
                  "strike_evidence": r.get("strike_evidence"), "notes": r.get("notes", "")}
            for rid, r in rows.items()}


def _line_for(text: str, rid: str) -> str | None:
    """The id's MEMBER row inside the class sections (an Appendix A3, A4 or B
    row carrying the same id is not a member row)."""
    for r in asm.scan_member_rows(text.split("\n")):
        if rid in r.ids:
            return r.line
    return None


def _index_for(text: str, rid: str) -> str | None:
    for ln in text.split("\n"):
        m = gen._APPENDIX_B_ROW.match(ln)
        if m and m.group(2) == rid:
            return ln
    return None


def _class_row(text: str, sec: str) -> str:
    return next(ln for ln in text.split("\n") if ln.startswith(f"| [{sec}]("))


def run(fin, rows, *, text=None, probe_ids=("DEF-1", "DEF-2", "DEF-3", "DEF-5", "DEF-9", "LG-9"), **kw):
    """The default probe roster carries no probe for the struck DEF-4: a probe on a
    struck row is roster drift the generator reports, and the live file has none."""
    return asm.assemble(text or ledger(), probes(*probe_ids), fin, rows, date=DATE, **kw)


# --------------------------------------------------------------------------
class TestCells:
    def test_only_unescaped_pipes_are_escaped_and_lines_are_flattened(self):
        assert asm.escape_cell("a | b") == r"a \| b"
        assert asm.escape_cell(r"already \| escaped") == r"already \| escaped"
        assert asm.escape_cell("two\n  lines  here") == "two lines here"

    def test_a_rebuilt_row_reparses_to_the_cell_count_it_claims_and_keeps_its_id_cell(self):
        row = asm.build_row("`DEF-1`", "a.py::f", "claim with a | pipe", "major", None)
        assert len(gen.member_cells(row)) == 4 and gen._MEMBER_ROW.match(row)
        row6 = asm.build_row("`DEF-9` `LG-9`", "a.py::f", "claim", "nit", ("HYGIENE", "OPERATOR"))
        assert gen.member_cells(row6)[0] == "`DEF-9` `LG-9`"
        assert gen.member_cells(row6)[4:] == ["HYGIENE", "OPERATOR"]

    def test_build_row_refuses_what_the_grammar_cannot_carry(self):
        with pytest.raises(asm.Refused):
            asm.build_row("`DEF-1`", "a.py::f", "", "major", None)
        with pytest.raises(asm.Refused):
            asm.build_row("`DEF-1`", "a.py::f", "claim", "urgent", None)
        with pytest.raises(asm.Refused):
            asm.build_row("`DEF-1`", "a.py::f", "claim", "nit", ("HYGIENE", "EVERYONE"))


class TestVerdicts:
    def test_a_keep_is_rewritten_with_its_pipe_escaped_and_its_index_anchor_synced(self):
        res = run(final(**{"DEF-1": dict(verdict="keep", severity="major")}),
                  lane(**{"DEF-1": dict(anchor="a.py::f (:3)", body="the claim: x | y hurts an adopter")}))
        assert _line_for(res.text, "DEF-1") == r"| `DEF-1` | a.py::f (:3) | the claim: x \| y hurts an adopter | major |"
        assert _index_for(res.text, "DEF-1") == "| `DEF-1` | §C1 | a.py::f (:3) |"
        assert res.report["keeps_written"] == 1 and res.report["index_anchors_synced"] == 1

    def test_a_keep_below_the_rows_severity_is_held_and_the_row_stays_byte_identical(self):
        res = run(final(**{"DEF-5": dict(verdict="keep", severity="nit", section="§C2")}),
                  lane(**{"DEF-5": dict(anchor="a", body="b")}))
        assert _line_for(res.text, "DEF-5") == C2_ROWS[0]
        assert res.report["severity_refused"] == ["DEF-5: nit is below the row's major"]
        assert "DEF-5" in res.report["held"] and res.report["keeps_written"] == 0

    def test_an_unreadable_severity_cell_is_held_not_overwritten(self):
        text = ledger().replace(C1_ROWS[2], "| `DEF-3` | site3 | what three | SOON |")
        res = run(final(**{"DEF-3": dict(verdict="keep", severity="nit")}),
                  lane(**{"DEF-3": dict(anchor="a", body="b")}), text=text)
        assert _line_for(res.text, "DEF-3") == "| `DEF-3` | site3 | what three | SOON |"
        assert res.report["severity_unreadable"] == ["DEF-3: severity cell 'SOON'"]

    def test_a_keep_whose_lane_text_is_missing_is_held(self):
        res = run(final(**{"DEF-1": dict(verdict="keep", severity="major")}), {})
        assert _line_for(res.text, "DEF-1") == C1_ROWS[0]
        assert res.report["keep_without_text"] == ["DEF-1"] and "DEF-1" in res.report["held"]

    def test_a_strike_deletes_the_row_tombstones_the_index_and_retires_the_probe(self):
        res = run(final(**{"DEF-2": dict(verdict="strike", probe="STRIKE_CANDIDATE")}),
                  lane(**{"DEF-2": dict(strike_evidence=EV)}))
        assert _line_for(res.text, "DEF-2") is None
        assert _index_for(res.text, "DEF-2") == "| ~~`DEF-2`~~ | §C1 | site |"
        assert "DEF-2" not in {p["id"] for p in res.probes["probes"]}
        assert res.probes["_count"] == len(res.probes["probes"])
        assert res.probes["_generated"] == f"{DATE} rebuild (third)"
        assert res.report["struck"] == ["DEF-2"] and res.report["probes_retired"] == ["DEF-2"]
        assert C1_ROWS[1] in res.struck_md and EV["driven_command"] in res.struck_md
        assert not [d for d in gen.find_drift(res.text) if d["region"] == "appendix-b-strike"]

    def test_a_two_id_row_keeps_both_ids_on_a_keep_and_tombstones_both_on_a_strike(self):
        keep = run(final(**{"DEF-9": dict(verdict="keep", severity="minor")}),
                   lane(**{"DEF-9": dict(anchor="a", body="b")}))
        assert _line_for(keep.text, "DEF-9") == "| `DEF-9` `LG-9` | a | b | minor |"
        assert _index_for(keep.text, "LG-9") == "| `LG-9` | §C1 | a |"
        assert keep.report["index_anchors_synced"] == 2 and keep.report["co_id_rows"] == ["DEF-9"]
        struck = run(final(**{"DEF-9": dict(verdict="strike")}), lane(**{"DEF-9": dict(strike_evidence=EV)}))
        assert _line_for(struck.text, "LG-9") is None
        assert _index_for(struck.text, "LG-9") == "| ~~`LG-9`~~ | §C1 | site |"
        assert set(struck.report["probes_retired"]) == {"DEF-9", "LG-9"}

    def test_a_verdict_keyed_on_the_second_id_reaches_its_row_and_a_conflict_is_held(self):
        via = run(final(**{"LG-9": dict(verdict="strike")}), lane(**{"LG-9": dict(strike_evidence=EV)}))
        assert _line_for(via.text, "DEF-9") is None and via.report["struck"] == ["DEF-9"]
        clash = run(final(**{"DEF-9": dict(verdict="keep", severity="minor"), "LG-9": dict(verdict="strike")}),
                    lane(**{"DEF-9": dict(anchor="a", body="b")}))
        assert _line_for(clash.text, "DEF-9") == C1_ROWS[3]
        assert clash.report["conflicting_verdicts"] == ["DEF-9: co-ids carry differing verdicts ['keep', 'strike']"]

    def test_an_extra_section_verdict_on_a_shared_co_id_is_the_twins_and_never_decides_or_holds_the_member_row(self):
        # The first real run: four kept §2 rows held as conflicts because the
        # extra lane's keep (encoded `unresolved`) on the §1 twin's co-id was
        # gathered as a second verdict on the member row.
        res = run(final(**{"DEF-9": dict(verdict="keep", severity="minor"),
                           "LG-9": dict(verdict="unresolved", section="extra", lane="extra-sections")}),
                  lane(**{"DEF-9": dict(anchor="a", body="b")}))
        assert _line_for(res.text, "DEF-9") == "| `DEF-9` `LG-9` | a | b | minor |"
        assert res.report["conflicting_verdicts"] == [] and res.report["unresolved"] == []
        assert "DEF-9" not in res.report["held"]
        assert res.report["co_id_extra_verdicts"] == [
            "DEF-9: LG-9 unresolved carries section 'extra' -- the extra-sections lane's verdict on the row "
            "outside the class sections that shares the id, not this row's"]
        assert S1_ROWS[2] in res.text  # the twin itself: an extra keep never rewrites

    def test_a_co_id_extra_verdict_with_no_extra_row_carrying_the_id_is_held_as_a_conflict(self):
        # Without the twin row the note would be untrue: nothing outside the
        # class sections carries LG-9, so the verdict is keyed nowhere.
        text = ledger().replace(S1_ROWS[2] + "\n", "")
        res = run(final(**{"DEF-9": dict(verdict="keep", severity="minor"),
                           "LG-9": dict(verdict="unresolved", section="extra", lane="extra-sections")}),
                  lane(**{"DEF-9": dict(anchor="a", body="b")}), text=text)
        assert _line_for(res.text, "DEF-9") == C1_ROWS[3]
        assert res.report["conflicting_verdicts"] == [
            "DEF-9: LG-9 unresolved carries section 'extra' but no row outside the class sections carries LG-9"]
        assert res.report["co_id_extra_verdicts"] == [] and "DEF-9" in res.report["held"]

    def test_a_first_id_verdict_whose_section_disclaims_the_row_is_held(self):
        # The census keys a live row by its first id; a verdict on that id
        # marked `extra` says it is about a row outside the class sections.
        res = run(final(**{"DEF-1": dict(verdict="keep", severity="major", section="extra")}),
                  lane(**{"DEF-1": dict(anchor="a", body="b")}))
        assert _line_for(res.text, "DEF-1") == C1_ROWS[0]
        assert res.report["section_disclaims_row"] == [
            "DEF-1: its own verdict carries section 'extra', which disclaims this row"]
        assert "DEF-1" in res.report["held"] and res.report["extra_unresolved"] == []

    def test_a_class_section_written_without_the_section_sign_is_still_a_class_verdict(self):
        # The adjudicator lanes wrote `C1` and `§C1` both (measured on the
        # first run: 11 `C0` beside 30 `§C0`). A strike for an id with no row
        # is reported as such under either spelling, never sent to the extra
        # pass; and a co-id's verdict spelled `C1` decides its member row,
        # with the lane text found under the row's first id.
        unknown = run(final(**{"DEF-99": dict(verdict="strike", section="C1")}),
                      lane(**{"DEF-99": dict(strike_evidence=EV)}))
        assert unknown.report["verdicts_for_unknown_ids"] == ["DEF-99"]
        assert unknown.report["extra_unresolved"] == []
        co_id = run(final(**{"LG-9": dict(verdict="keep", severity="minor", section="C1")}),
                    lane(**{"LG-9": dict(), "DEF-9": dict(anchor="a", body="b")}))
        assert _line_for(co_id.text, "DEF-9") == "| `DEF-9` `LG-9` | a | b | minor |"
        assert co_id.report["keep_without_text"] == [] and co_id.report["co_id_extra_verdicts"] == []
        evidence = run(final(**{"LG-9": dict(verdict="strike", section="C1")}),
                       lane(**{"LG-9": dict(), "DEF-9": dict(strike_evidence=EV)}))
        assert evidence.report["struck"] == ["DEF-9"] and EV["driven_command"] in evidence.struck_md

    def test_a_fold_deletes_tombstones_retires_and_writes_the_a4_row_inside_the_a4_table(self):
        res = run(final(**{"DEF-3": dict(verdict="fold", fold_into="DEF-1"),
                           "DEF-1": dict(verdict="keep", severity="major")}),
                  lane(**{"DEF-1": dict(anchor="a", body="b")}))
        assert _line_for(res.text, "DEF-3") is None
        assert _index_for(res.text, "DEF-3") == "| ~~`DEF-3`~~ | §C1 | site |"
        lines = res.text.split("\n")
        a4 = [ln for ln in lines if ln.startswith("| `DEF-3` (§C1) -- folded")]
        assert a4 and a4[0].endswith("| **`DEF-1`** |")
        i = lines.index(a4[0])
        assert lines[i - 1].startswith("|") and lines.index("## Appendix A4 - re-keyed ids") < i < lines.index("## Appendix B - id index")
        assert res.report["folded"] == ["DEF-3 -> DEF-1"]
        assert "DEF-3" not in {p["id"] for p in res.probes["probes"]}

    def test_a_fold_into_a_row_that_leaves_or_into_itself_is_held(self):
        res = run(final(**{"DEF-3": dict(verdict="fold", fold_into="DEF-2"), "DEF-2": dict(verdict="strike"),
                           "DEF-9": dict(verdict="fold", fold_into="LG-9")}),
                  lane(**{"DEF-2": dict(strike_evidence=EV)}))
        assert _line_for(res.text, "DEF-3") == C1_ROWS[2] and _line_for(res.text, "DEF-9") == C1_ROWS[3]
        assert res.report["fold_refused"] == ["DEF-3: fold_into 'DEF-2' is not a live row that stays",
                                              "DEF-9: fold_into 'LG-9' is not a live row that stays"]

    def test_a_fold_with_no_a4_table_is_held_and_lands_nowhere_else(self):
        text = ledger().replace("| citation as written | what it meant | reads today |\n|---|---|---|\n"
                                "| `DEF-0` (§C1) — an old cite | the old row | **`DEF-1`** |\n", "")
        res = run(final(**{"DEF-3": dict(verdict="fold", fold_into="DEF-1")}), {}, text=text)
        assert "folded" not in res.text
        assert res.report["fold_refused"] == ["Appendix A4 has no table to append to; the fold rows were not written"]
        assert _line_for(res.text, "DEF-3") is None  # the row itself still left

    def test_unresolved_and_unverdicted_rows_are_byte_identical_and_named(self):
        res = run(final(**{"DEF-6": dict(verdict="unresolved", section="§C2")}), {})
        assert _line_for(res.text, "DEF-6") == C2_ROWS[1] and _line_for(res.text, "DEF-8") == C0_ROWS[1]
        assert res.report["unresolved"] == ["DEF-6"]
        live_ids = [r.id for r in asm.scan_member_rows(ledger().split("\n")) if not r.struck]
        assert set(res.report["no_verdict"]) == set(live_ids) - {"DEF-6"}
        assert res.report["held"] == sorted(live_ids)

    def test_final_decides_not_the_lane_file(self):
        res = run(final(**{"DEF-1": dict(verdict="keep", severity="major")}),
                  lane(**{"DEF-1": dict(anchor="a", body="b", strike_evidence=EV)}))
        assert _line_for(res.text, "DEF-1") == "| `DEF-1` | a | b | major |" and res.report["struck"] == []

    def test_previously_struck_rows_are_retained_by_default_and_moved_only_on_request(self):
        with_stale_probe = ("DEF-1", "DEF-4")
        kept = run(final(), {}, probe_ids=with_stale_probe)
        assert _line_for(kept.text, "DEF-4") == C1_ROWS[4] and kept.report["previously_struck_dropped"] == 0
        assert "DEF-4" in {p["id"] for p in kept.probes["probes"]}  # retained row, retained probe: 1-D's call
        moved = run(final(), {}, probe_ids=with_stale_probe, drop_previously_struck=True)
        assert _line_for(moved.text, "DEF-4") is None and moved.report["previously_struck_dropped"] == 1
        assert "Previously struck" in moved.struck_md and C1_ROWS[4] in moved.struck_md
        assert "DEF-4" not in {p["id"] for p in moved.probes["probes"]}

    def test_a_verdict_for_an_id_with_no_row_is_reported(self):
        res = run(final(**{"DEF-99": dict(verdict="keep", severity="nit")}), lane(**{"DEF-99": dict(anchor="a", body="b")}))
        assert res.report["verdicts_for_unknown_ids"] == ["DEF-99"]


class TestClassTags:
    def test_agreement_on_one_axis_rewrites_that_index_cell_only_with_provenance(self):
        fin = final(**{rid: dict(verdict="keep", severity=sev, audience="MAINTAINER")
                       for rid, sev in (("DEF-1", "major"), ("DEF-2", "minor"), ("DEF-3", "nit"), ("DEF-9", "minor"))})
        res = run(fin, lane(**{rid: dict(anchor="a", body="b") for rid in ("DEF-1", "DEF-2", "DEF-3", "DEF-9")}))
        idx = _class_row(res.text, "§C1")
        assert idx.split("|")[4].strip() == "LOGIC_BUG"
        assert idx.split("|")[5].strip() == f"MAINTAINER (re-derived {DATE}; was ADOPTER)"
        assert gen.declared_class_tags(res.text)["§C1"] == ("LOGIC_BUG", "MAINTAINER")
        assert res.report["class_tag_changes"] == [{"section": "§C1", "axis": "audience", "was": "ADOPTER", "now": "MAINTAINER"}]
        assert res.report["mixed_axes"] == []
        assert all(len(gen.member_cells(_line_for(res.text, r))) == 4 for r in ("DEF-1", "DEF-2", "DEF-3", "DEF-9"))
        d = gen.derive(res.text)
        assert d["tag_problems"] == [] and d["audience_live"]["ADOPTER"] == 1  # DEF-11 only

    def test_disagreement_on_one_axis_makes_that_axis_mixed_and_widens_the_untouched_rows(self):
        fin = final(**{"DEF-1": dict(verdict="keep", severity="major", audience="ADOPTER"),
                       "DEF-2": dict(verdict="keep", severity="minor", audience="MAINTAINER"),
                       "DEF-3": dict(verdict="unresolved"),
                       "DEF-9": dict(verdict="keep", severity="minor", audience="ADOPTER")})
        res = run(fin, lane(**{r: dict(anchor="a", body="b") for r in ("DEF-1", "DEF-2", "DEF-9")}))
        assert gen.declared_class_tags(res.text)["§C1"] == ("LOGIC_BUG", gen.MIXED)
        assert _class_row(res.text, "§C1").split("|")[4].strip() == "LOGIC_BUG"
        assert gen.member_cells(_line_for(res.text, "DEF-2"))[4:] == ["LOGIC_BUG", "MAINTAINER"]
        assert _line_for(res.text, "DEF-3") == C1_ROWS[2] + " LOGIC_BUG | ADOPTER |"
        assert res.report["widened_rows"] == ["DEF-3: LOGIC_BUG | ADOPTER"]
        assert res.report["mixed_axes"] == [{"section": "§C1", "axis": "audience", "was": "ADOPTER", "tokens": ["ADOPTER", "MAINTAINER"]}]
        d = gen.derive(res.text)
        maintainers = (1  # DEF-2, relabelled
                       + sum(1 for r in C0_ROWS if "| MAINTAINER |" in r)
                       + _live(C2_ROWS)
                       + sum(1 for r in C3_ROWS if "| MAINTAINER |" in r))
        assert d["tag_problems"] == [] and d["audience_live"]["MAINTAINER"] == maintainers

    def test_a_held_row_with_final_labels_is_widened_with_them_not_the_old_class_tags(self):
        fin = final(**{"DEF-1": dict(verdict="keep", severity="major", audience="MAINTAINER"),
                       "DEF-2": dict(verdict="keep", severity="minor", audience="ADOPTER"),
                       "DEF-3": dict(verdict="keep", severity="blocker", audience="OPERATOR"),  # held: blocker above nit
                       "DEF-9": dict(verdict="unresolved")})
        res = run(fin, lane(**{r: dict(anchor="a", body="b") for r in ("DEF-1", "DEF-2", "DEF-3")}))
        assert res.report["severity_refused"] == []  # blocker is ABOVE nit: allowed
        assert gen.member_cells(_line_for(res.text, "DEF-3"))[4:] == ["LOGIC_BUG", "OPERATOR"]
        assert _line_for(res.text, "DEF-9") == C1_ROWS[3] + " LOGIC_BUG | ADOPTER |"

    def test_a_class_mixed_on_one_axis_keeps_its_rows_own_cell_on_that_axis(self):
        fin = final(**{"DEF-11": dict(verdict="keep", severity="minor", section="§C3", audience="OPERATOR"),
                       "DEF-12": dict(verdict="keep", severity="nit", section="§C3")})
        res = run(fin, lane(**{"DEF-11": dict(anchor="a", body="b"), "DEF-12": dict(anchor="c", body="d")}))
        assert _line_for(res.text, "DEF-11") == "| `DEF-11` | a | b | minor | HYGIENE | OPERATOR |"
        assert _line_for(res.text, "DEF-12") == "| `DEF-12` | c | d | nit | HYGIENE | MAINTAINER |"
        assert gen.declared_class_tags(res.text)["§C3"] == ("HYGIENE", gen.MIXED)
        d = gen.derive(res.text)
        assert d["tag_problems"] == [] and d["audience_live"]["OPERATOR"] == 2

    def test_disagreement_on_the_fixed_axis_of_a_half_mixed_class_flips_it_to_fully_mixed(self):
        fin = final(**{"DEF-11": dict(verdict="keep", severity="minor", section="§C3", population="LOGIC_BUG"),
                       "DEF-12": dict(verdict="keep", severity="nit", section="§C3", population="HYGIENE")})
        res = run(fin, lane(**{"DEF-11": dict(anchor="a", body="b"), "DEF-12": dict(anchor="c", body="d")}))
        assert gen.declared_class_tags(res.text)["§C3"] == (gen.MIXED, gen.MIXED)
        assert gen.member_cells(_line_for(res.text, "DEF-11"))[4:] == ["LOGIC_BUG", "ADOPTER"]
        assert gen.derive(res.text)["tag_problems"] == []

    def test_a_placeholder_class_tag_refuses_its_keeps_and_writes_no_none(self):
        fin = final(**{"DEF-5": dict(verdict="keep", severity="major", section="§C2", population="HYGIENE"),
                       "DEF-6": dict(verdict="keep", severity="minor", section="§C2")})
        res = run(fin, lane(**{"DEF-5": dict(anchor="a", body="b"), "DEF-6": dict(anchor="c", body="d")}),
                  text=ledger(c2_tags=("—", "—")))
        assert _line_for(res.text, "DEF-5") == C2_ROWS[0] and _line_for(res.text, "DEF-6") == C2_ROWS[1]
        assert len(res.report["row_refused"]) == 2 and "None" not in res.text
        assert set(res.report["held"]) >= {"DEF-5", "DEF-6"}

    def test_a_keep_in_a_fully_mixed_class_carries_its_own_final_tags(self):
        fin = final(**{"DEF-7": dict(verdict="keep", severity="minor", section="§C0", population="LOGIC_BUG", audience="ADOPTER")})
        res = run(fin, lane(**{"DEF-7": dict(anchor="a", body="b")}))
        assert _line_for(res.text, "DEF-7") == "| `DEF-7` | a | b | minor | LOGIC_BUG | ADOPTER |"
        assert gen.derive(res.text)["tag_problems"] == []


class TestExtraSections:
    def test_a_two_id_section_one_row_needs_a_strike_for_every_id(self):
        one = run(final(**{"DEF-537": dict(verdict="strike", section="extra")}), {}, probe_ids=("DEF-537", "LG-3"))
        assert S1_ROWS[0] in one.text
        assert one.report["extra_unresolved"] == ["DEF-537: its row also carries ['LG-3'] without a strike verdict; the row stays"]
        both = run(final(**{"DEF-537": dict(verdict="strike", section="extra"), "LG-3": dict(verdict="strike", section="extra")}),
                   {}, probe_ids=("DEF-537", "LG-3"))
        assert S1_ROWS[0] not in both.text and S1_ROWS[1] in both.text
        assert both.report["extra_struck"] == ["DEF-537", "LG-3"] and both.probes["probes"] == []
        assert S1_ROWS[0] in both.struck_md

    def test_a_twin_row_leaves_only_with_its_member_row(self):
        # Strike both ids or neither: an extra strike on the co-id alone is
        # refused while the member row lives -- and the member row is still
        # decided on its own verdict, not held. (The first cut of this fix
        # let the twin go and kept the pair alive; both reviews caught it on
        # launch gate 2 of the real file.)
        alone = run(final(**{"DEF-9": dict(verdict="keep", severity="minor"),
                             "LG-9": dict(verdict="strike", section="extra", lane="extra-sections")}),
                    lane(**{"DEF-9": dict(anchor="a", body="b"), "LG-9": dict(strike_evidence=EV)}))
        assert S1_ROWS[2] in alone.text and S1_ROWS[2] not in alone.struck_md
        assert _line_for(alone.text, "DEF-9") == "| `DEF-9` `LG-9` | a | b | minor |"
        assert _index_for(alone.text, "LG-9") == "| `LG-9` | §C1 | a |"
        assert {p["id"] for p in alone.probes["probes"]} >= {"DEF-9", "LG-9"}
        assert alone.report["extra_unresolved"] == [
            "LG-9: its row also carries ['DEF-9'] without a strike verdict; the row stays"]
        assert alone.report["extra_struck"] == [] and "DEF-9" not in alone.report["held"]
        # Both struck in one run: the member row retires the pair; the twin goes too.
        both = run(final(**{"DEF-9": dict(verdict="strike"),
                            "LG-9": dict(verdict="strike", section="extra", lane="extra-sections")}),
                   lane(**{"DEF-9": dict(strike_evidence=EV), "LG-9": dict(strike_evidence=EV)}))
        assert _line_for(both.text, "DEF-9") is None and S1_ROWS[2] not in both.text
        assert _index_for(both.text, "LG-9") == "| ~~`LG-9`~~ | §C1 | site |"
        assert set(both.report["probes_retired"]) == {"DEF-9", "LG-9"} and "DEF-9" not in both.report["held"]
        assert both.report["extra_unresolved"] == [] and both.report["extra_rows_citing_retired_ids"] == []

    def test_a_member_strike_whose_twin_stays_is_reported_not_held(self):
        # The strike verb's own precedent (DEF-538+LG-5): the member row goes,
        # both ids are tombstoned, and the §1 row still carrying them is the
        # structural cut's decision -- named and counted, the run still writes.
        res = run(final(**{"DEF-9": dict(verdict="strike"),
                           "LG-9": dict(verdict="unresolved", section="extra", lane="extra-sections")}),
                  lane(**{"DEF-9": dict(strike_evidence=EV)}))
        assert _line_for(res.text, "DEF-9") is None and S1_ROWS[2] in res.text
        assert _index_for(res.text, "LG-9") == "| ~~`LG-9`~~ | §C1 | site |"
        twin_line = ledger().split("\n").index(S1_ROWS[2]) + 1
        assert res.report["extra_rows_citing_retired_ids"] == [
            f"line {twin_line}: still carries retired ['DEF-9', 'LG-9']"]
        assert "DEF-9" not in res.report["held"]

    def test_an_illegal_extra_lane_verdict_is_held_not_dropped(self):
        # The lane is told keep-or-strike; a fold that slips through the
        # workflow's normaliser is a refusal, not a footnote.
        res = run(final(**{"TP-9": dict(verdict="fold", fold_into="TP-10", section="extra")}), {})
        assert S3_ROWS[0] in res.text
        assert res.report["extra_unresolved"] == [
            "TP-9: fold is not a verdict the extra-sections lane returns (keep or strike only); the row stays"]
        assert "TP-9" in res.report["held"]

    def test_a_struck_member_rows_first_id_is_the_extra_lanes_key(self):
        # The census holds LIVE rows only, so the extra lane legitimately owns
        # the first id of a previously struck member row (DEF-538 today); a
        # strike on it reaches the §1 row instead of being swallowed.
        done = "| 4 | `DEF-4` | the done cut |"
        text = ledger().replace(S1_ROWS[1], S1_ROWS[1] + "\n" + done)
        res = run(final(**{"DEF-4": dict(verdict="strike", section="extra", lane="extra-sections")}),
                  lane(**{"DEF-4": dict(strike_evidence=EV)}), text=text)
        assert done not in res.text and done in res.struck_md
        assert res.report["extra_struck"] == ["DEF-4"] and res.report["extra_unresolved"] == []
        assert _line_for(res.text, "DEF-4") == C1_ROWS[4]  # the struck member row is untouched

    def test_a_section_three_row_is_struck_and_the_appendices_are_never_touched(self):
        fin = final(**{"TP-9": dict(verdict="strike", section="extra"), "DEC-8": dict(verdict="strike", section="extra")})
        res = run(fin, {})
        assert S3_ROWS[0] not in res.text and S3_ROWS[1] in res.text and A3_ROW in res.text
        assert res.report["extra_struck"] == ["TP-9"]
        assert res.report["extra_unresolved"] == ["DEC-8: no unique row outside the class sections"]

    def test_an_ambiguous_or_absent_extra_id_is_reported_and_nothing_is_deleted(self):
        text = ledger().replace(S3_ROWS[1], S3_ROWS[1] + "\n" + S3_ROWS[0])
        fin = final(**{"TP-9": dict(verdict="strike", section="extra"), "TP-404": dict(verdict="strike", section="extra")})
        res = run(fin, {}, text=text)
        assert res.text.count(S3_ROWS[0]) == 2
        assert res.report["extra_unresolved"] == ["TP-9: no unique row outside the class sections",
                                                  "TP-404: no unique row outside the class sections"]

    def test_an_extra_keep_never_rewrites(self):
        res = run(final(**{"TP-9": dict(verdict="keep", section="extra")}), lane(**{"TP-9": dict(anchor="x", body="y")}))
        assert S3_ROWS[0] in res.text and res.report["keeps_written"] == 0


class TestRegionsAndDeterminism:
    def test_the_regions_converge_and_the_probe_reader_is_restored(self):
        fin = final(**{"DEF-1": dict(verdict="keep", severity="major"), "DEF-2": dict(verdict="strike"),
                       "DEF-3": dict(verdict="fold", fold_into="DEF-1"), "DEF-6": dict(verdict="unresolved", section="§C2")})
        res = run(fin, lane(**{"DEF-1": dict(anchor="a", body="b"), "DEF-2": dict(strike_evidence=EV)}))
        before = gen._probe_ids
        text, residual = asm.regenerate_regions(res.text, {p["id"] for p in res.probes["probes"]})
        assert gen._probe_ids is before
        assert residual == []
        d = gen.derive(text)
        expected = sum(_live(r) for r in SECTIONS.values()) - 2  # one struck, one folded
        assert d["live_total"] == res.report["live_after"] == expected
        assert f"**Live: {expected}**" in text

    def test_live_after_is_derived_from_the_rows_not_typed(self):
        fin = final(**{"DEF-2": dict(verdict="strike"), "DEF-3": dict(verdict="fold", fold_into="DEF-1")})
        res = run(fin, lane(**{"DEF-2": dict(strike_evidence=EV)}))
        expected = sum(_live(r) for r in SECTIONS.values()) - 2
        assert res.report["live_before"] == expected + 2
        assert res.report["live_after"] == gen.derive(res.text)["live_total"] == expected

    def test_the_same_inputs_give_the_same_bytes(self):
        fin = final(**{"DEF-1": dict(verdict="keep", severity="major"), "DEF-2": dict(verdict="strike")})
        rows = lane(**{"DEF-1": dict(anchor="a", body="b"), "DEF-2": dict(strike_evidence=EV)})
        a, b = run(fin, rows), run(fin, rows)
        assert (a.text, a.struck_md, json.dumps(a.probes, sort_keys=True), json.dumps(a.report, sort_keys=True)) == \
               (b.text, b.struck_md, json.dumps(b.probes, sort_keys=True), json.dumps(b.report, sort_keys=True))


class TestInputs:
    def test_final_accepts_a_list_or_a_wrapper_and_refuses_bad_shapes(self):
        lst = final(**{"DEF-1": dict(verdict="keep", severity="major")})
        assert asm.load_final(lst) == lst and asm.load_final({"verdicts": lst}) == lst
        for bad in ({"id": "DEF-1", "verdict": "maybe"}, {"verdict": "keep"},
                    {"id": "DEF-1", "verdict": "keep", "severity": "urgent"},
                    {"id": "DEF-1", "verdict": "keep", "audience": "MIXED"}):
            with pytest.raises(ValueError):
                asm.load_final([bad])
        with pytest.raises(ValueError):
            asm.load_final(lst + lst)

    def test_final_refuses_a_section_that_is_neither_a_class_section_nor_extra(self):
        # `section` routes a verdict to its row since the twin fix, so a
        # spelling the router cannot read is a malformed input, not a hold.
        for ok in ("§C1", "C12", "extra"):
            assert asm.load_final([{"id": "DEF-1", "verdict": "keep", "section": ok}])[0]["section"] == ok
        for bad in ("", None, "§1B step 5", "C", "C1x"):
            with pytest.raises(ValueError):
                asm.load_final([{"id": "DEF-1", "verdict": "keep", "section": bad}])

    def test_a_probes_file_whose_count_disagrees_with_its_rows_is_refused(self):
        assert asm.load_probes(probes("DEF-1"))["_count"] == 1
        bad = probes("DEF-1"); bad["_count"] = 2
        with pytest.raises(ValueError):
            asm.load_probes(bad)
        with pytest.raises(ValueError):
            asm.load_probes({"nope": []})

    def test_lane_rows_prefer_the_first_entry_that_carries_a_row(self, tmp_path):
        (tmp_path / "census.json").write_text(json.dumps({"ids": ["DEF-1"]}), encoding="utf-8")
        (tmp_path / "adjudicate-0.json").write_text(json.dumps({"verdicts": [
            {"id": "DEF-1", "verdict": "unresolved"}]}), encoding="utf-8")
        (tmp_path / "adjudicate-1.json").write_text(json.dumps({"verdicts": [
            {"id": "DEF-1", "verdict": "keep", "row": {"anchor": "a1", "body": "b1"}}]}), encoding="utf-8")
        (tmp_path / "adjudicate-2.json").write_text(json.dumps({"verdicts": [
            {"id": "DEF-1", "verdict": "keep", "row": {"anchor": "a2", "body": "b2"}}]}), encoding="utf-8")
        rows, dups = asm.load_lane_rows(tmp_path)
        assert rows["DEF-1"]["anchor"] == "a1" and rows["DEF-1"]["lane"] == "adjudicate-1"
        assert dups == ["DEF-1 (adjudicate-1 kept -- it carries the row; adjudicate-0 did not)",
                        "DEF-1 (adjudicate-1 kept; adjudicate-2 ignored)"]
        (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError):
            asm.load_lane_rows(tmp_path)


class TestCli:
    def _tree(self, tmp_path, fin_doc, *, probe_doc=None):
        (tmp_path / "FORWARD_LEDGER.md").write_text(ledger(), encoding="utf-8")
        (tmp_path / "LEDGER_PROBES.json").write_text(json.dumps(probe_doc or probes("DEF-1", "DEF-2")), encoding="utf-8")
        lanes = tmp_path / "lanes"; lanes.mkdir()
        (lanes / "adjudicate-0.json").write_text(json.dumps({"verdicts": [
            {"id": "DEF-1", "verdict": "keep", "row": {"anchor": "a.py::f", "body": "the claim"}},
            {"id": "DEF-2", "verdict": "strike", "strike_evidence": EV}]}), encoding="utf-8")
        (tmp_path / "final.json").write_text(json.dumps(fin_doc), encoding="utf-8")
        return ["--ledger", str(tmp_path / "FORWARD_LEDGER.md"), "--probes", str(tmp_path / "LEDGER_PROBES.json"),
                "--lanes", str(lanes), "--final", str(tmp_path / "final.json"), "--out", str(tmp_path / "out")]

    def test_held_rows_above_the_limit_refuse_the_run_and_write_nothing(self, tmp_path, capsys):
        args = self._tree(tmp_path, final(**{"DEF-1": dict(verdict="keep", severity="major"), "DEF-2": dict(verdict="strike")}))
        assert asm.main(args + ["--date", DATE]) == 3
        assert not (tmp_path / "out").exists()
        err = capsys.readouterr().err
        assert "above --max-held 0" in err and "no_verdict: DEF-3" in err

    def test_it_writes_the_four_outputs_and_the_output_converges(self, tmp_path, capsys, monkeypatch):
        args = self._tree(tmp_path, final(**{"DEF-1": dict(verdict="keep", severity="major"), "DEF-2": dict(verdict="strike")}))
        out = tmp_path / "out"
        assert asm.main(args + ["--date", DATE, "--max-held", "20"]) == 0
        assert {p.name for p in out.iterdir()} == set(asm.OUTPUT_NAMES)
        report = json.loads((out / "assemble-report.json").read_text(encoding="utf-8"))
        assert report["residual_drift"] == [] and report["struck"] == ["DEF-2"] and report["keeps_written"] == 1
        rebuilt = (out / "FORWARD_LEDGER.rebuilt.md").read_text(encoding="utf-8")
        probe_ids = {p["id"] for p in json.loads((out / "LEDGER_PROBES.rebuilt.json").read_text(encoding="utf-8"))["probes"]}
        monkeypatch.setattr(gen, "_probe_ids", lambda: probe_ids)
        assert gen.find_drift(rebuilt) == []
        assert (tmp_path / "FORWARD_LEDGER.md").read_text(encoding="utf-8") == ledger()
        assert "assembled" in capsys.readouterr().out

    def test_a_second_run_into_the_same_out_is_refused_unless_forced(self, tmp_path):
        args = self._tree(tmp_path, final(**{"DEF-1": dict(verdict="keep", severity="major")})) + ["--date", DATE, "--max-held", "20"]
        assert asm.main(args) == 0
        payload = (tmp_path / "out" / "struck-rows.md").read_bytes()
        assert asm.main(args) == 3
        assert (tmp_path / "out" / "struck-rows.md").read_bytes() == payload
        assert asm.main(args + ["--force"]) == 0

    def test_a_malformed_input_exits_2_and_writes_nothing(self, tmp_path):
        args = self._tree(tmp_path, [{"id": "DEF-1", "verdict": "maybe"}])
        assert asm.main(args + ["--date", DATE]) == 2 and not (tmp_path / "out").exists()
        (tmp_path / "final.json").write_text("[]", encoding="utf-8")
        assert asm.main(args + ["--date", "today"]) == 2 and not (tmp_path / "out").exists()
        bad = probes("DEF-1"); bad["_count"] = 9
        (tmp_path / "LEDGER_PROBES.json").write_text(json.dumps(bad), encoding="utf-8")
        assert asm.main(args + ["--date", DATE]) == 2 and not (tmp_path / "out").exists()

    def test_a_file_with_no_class_sections_is_refused_with_exit_1(self, tmp_path):
        args = self._tree(tmp_path, [])
        (tmp_path / "FORWARD_LEDGER.md").write_text("# not a ledger\n", encoding="utf-8")
        assert asm.main(args + ["--date", DATE]) == 1 and not (tmp_path / "out").exists()

    def test_the_drop_flag_moves_previously_struck_rows(self, tmp_path):
        args = self._tree(tmp_path, final()) + ["--date", DATE, "--max-held", "20", "--drop-previously-struck"]
        assert asm.main(args) == 0
        rebuilt = (tmp_path / "out" / "FORWARD_LEDGER.rebuilt.md").read_text(encoding="utf-8")
        assert _line_for(rebuilt, "DEF-4") is None
        assert C1_ROWS[4] in (tmp_path / "out" / "struck-rows.md").read_text(encoding="utf-8")
