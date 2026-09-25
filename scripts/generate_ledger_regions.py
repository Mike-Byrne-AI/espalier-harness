#!/usr/bin/env python3
"""Derive ``task-packs/FORWARD_LEDGER.md``'s claimed-generated regions from its member rows.

Why this exists
---------------
The ledger asserts, in four separate places, that its summary regions are
generated (and since 2026-09-08 the §2 population and audience tables and the
headline's split and adopter figure are derived here too -- see POPULATIONS /
AUDIENCES below; before that the adopter figure was typed, and read 62 through
63 closures):

* *"The §2 headline, the class index, the per-class member counts and Appendix B
  are all computed from the member rows at generation time."*
* *"Never hand-edit a count here -- regenerate."*
* Appendix B: *"it is GENERATED from the member rows, so it cannot drift from
  them."*
* forty-eight ``**Members (N)** -- derived, never typed`` lines.

**No generator existed.** ``command grep -rln FORWARD_LEDGER scripts/ tools/
espalier/`` returned two read-only checkers and nothing that writes. Every one of
those regions was hand-kept, and on 2026-09-02 five of them had drifted:

===========================  ==========================================
region                       drift measured at 2026-09-02
===========================  ==========================================
top-of-file headline         said ``Live: 168``; sections carried 174
inline ``**Members (N)**``   §C0 said 31 against 37 rows
Appendix B strike markers    12 ids struck in §C, unstruck in the index
class-index live splits      §C0/§C3/§C4/§C5 hid 11 struck rows
probe roster                 14 probes still aimed at struck rows
===========================  ==========================================

§C3 was the sharpest: every one of its three members is struck, yet the class
index still presented it as a live 3-member ADOPTER logic-bug class with a ~100
LOC estimate, because its cell is a bare number and
``test_declared_live_splits_match_the_struck_rows`` skips any cell that does not
declare a ``(N live, M closed)`` split.

The parsers live HERE, not in the test module
---------------------------------------------
``tests/test_forward_ledger_completeness.py`` owned ``_ledger_sections``,
``_declared_class_table`` and ``_live_member_ids``. A generator needs exactly
those, and re-implementing them would have created a second hand-kept copy of the
ledger's grammar -- the defect class this script exists to close, one layer up.
So this module is their single home and the test imports them, which also means
the suite validates the generator's parsing for free.

``--check`` is the deliverable; ``--write`` is the convenience
-------------------------------------------------------------
A generator nobody runs is a ninth ungated summary. The gate is
``tests/test_generate_ledger_regions.py``, which runs ``--check`` against the
live ledger, so drift cannot land green. This mirrors how
``scripts/generate_doc_regions.py`` is enforced by ``tests/test_doc_regions.py``.

Self-host only: ``task-packs/`` is absent from an adopter tree, so a missing
ledger exits 0 with a note rather than failing.

Usage::

    python3 scripts/generate_ledger_regions.py            # report drift
    python3 scripts/generate_ledger_regions.py --check    # exit 1 on drift
    python3 scripts/generate_ledger_regions.py --write    # repair in place
    python3 scripts/generate_ledger_regions.py --json     # machine-readable

Exit codes: 0 = converged (or nothing to do), 1 = drift found under ``--check``
or the ledger could not be parsed, 2 = usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_LEDGER = _ROOT / "task-packs" / "FORWARD_LEDGER.md"
_PROBES = _ROOT / "task-packs" / "LEDGER_PROBES.json"

# --------------------------------------------------------------------------
# The ledger's grammar. Single home -- the test module imports these.
# --------------------------------------------------------------------------

#: The anchor is the heading's rendered slug (`#c14--make-two-gates-...`) since
#: 2026-09-21, when the ledger started shipping and its 33 bare `#c14` links
#: turned out to resolve to no heading on a GitHub render; the bare form is
#: still accepted so an older snapshot parses.
_CLASS_TABLE_ROW = re.compile(r"^\|\s*\[(§C\d+)\]\(#c\d+[\w-]*\)\s*\|")
_SECTION_HEADING = re.compile(r"^### (§C\d+)\b")
#: A member row: a table row whose first cell opens with a backticked id or a
#: struck id. Excludes header/separator rows and prose.
_MEMBER_ROW = re.compile(r"^\|\s*(~~)?`")
#: The first cell's id, struck or not.
_MEMBER_ID = re.compile(r"^\|\s*(~~)?`([^`]+)`")
#: Every backticked token inside one cell.
_CELL_ID = re.compile(r"`([^`]+)`")
#: The shape of a ledger id (``DEF-536``, ``LG-1``, ``DEF-371a``, ``PR-3``; a
#: pack id in an id cell has the same shape).
#: One home: ``ledger_structural_cut.py`` reads its ``_ID_SHAPE`` from here.
_ID_SHAPE = re.compile(r"^[A-Z]{2,5}-\d+[a-z]*$")
#: A ``~~...~~`` struck span inside a cell.
_STRUCK_SPAN = re.compile(r"~~[^~]*~~")


def cell_ids(row: str) -> list[str]:
    """Every id-shaped token in ``row``'s FIRST cell, struck or not, in cell
    order; ``[]`` for a line that is not a member or index row.

    A row is COUNTED once, by its first id (``_MEMBER_ID``, ``live_member_ids``),
    but it is ADDRESSED by any id its cell carries: ``ledger_row.py``'s verbs
    and ``check_ledger_probes.py``'s lookups take an id and find the row. Until
    2026-09-20 each demanded a lone id before the pipe, so a two-id row
    (``| `DEF-536` `LG-1` | ...``, eight live rows) was invisible to strike,
    repin, ``file --after`` and the staleness axis by EITHER id (``DEF-863``).
    The first cell ends at the first unescaped pipe, so an id quoted in the
    text cell is never read as an address; a backticked path or word in the
    cell (the Appendix A crosswalks carry ``cc/GOAL.md``, 38 such tokens on
    2026-09-20) is not an id and is never handed to a verb that would rebuild
    the cell from this list. Appendix B index rows carry ONE id per row (0 of
    164 carried two on 2026-09-20); ``_APPENDIX_B_ROW`` and the verbs'
    ``_index_line`` read that shape and would miss a two-id index row.
    """
    if not _MEMBER_ROW.match(row):
        return []
    first = re.split(r"(?<!\\)\|", row.strip()[1:], maxsplit=1)[0]
    return [tok for tok in _CELL_ID.findall(first) if _ID_SHAPE.match(tok)]


def half_struck(row: str) -> bool:
    """True when SOME but not all ids of ``row``'s first cell sit inside a
    ``~~`` span (``| `DEF-3` ~~`DEF-4`~~ | ...``). Strike state is read at row
    level everywhere else (``_is_struck``: the cell's leading marker), and a
    strike rewrites the whole cell, so a verb that met this shape would close a
    live co-id as collateral or hide one from the staleness axis. No such row
    exists on 2026-09-20 (0 of 534 live-file and 150 rebuilt member rows); the
    verbs refuse it rather than guess."""
    ids = cell_ids(row)
    if not ids:
        return False
    first = re.split(r"(?<!\\)\|", row.strip()[1:], maxsplit=1)[0]
    live = [tok for tok in _CELL_ID.findall(_STRUCK_SPAN.sub("", first)) if _ID_SHAPE.match(tok)]
    return 0 < len(live) < len(ids)


#: The inline per-section count line.
_MEMBERS_LINE = re.compile(r"^\*\*Members \((\d+)\)\*\*")
#: The top-of-file headline.
_HEADLINE = re.compile(r"^\*\*Live: (\d+)\*\*")
#: §2's own header: the live total, the classes with live rows, and the
#: standalone (MIXED-class) live rows -- all three derived. The last two were
#: typed and read "47 classes + 30 standalone" over 45 and 37 (review round).
_SECTION2_HEADER = re.compile(
    r"^##\s*§2[^\n]*?\((\d+) LIVE issues in (\d+) classes \+ (\d+) standalone\)"
)
#: An Appendix B index row: ``| `DEF-1` | §C9 | site |``
_APPENDIX_B_ROW = re.compile(r"^\|\s*(~~)?`([^`]+)`(~~)?\s*\|\s*(§C\d+)\s*\|")

# The two classifications every live row carries, and the ONLY spellings.
# A classed row inherits both from its class-index row; a row in a class the
# index marks MIXED carries its own two cells (`| ... | sev | pop | aud |`).
# The §2 population and audience tables and the headline split are derived
# from these -- they were hand-typed until 2026-09-08, and the audience
# figure sat at 62 through 63 closures because nothing re-derived it.
POPULATIONS = ("LOGIC_BUG", "HYGIENE", "OPERATOR_ACTION")
AUDIENCES = ("ADOPTER", "MAINTAINER", "OPERATOR")
MIXED = "MIXED"
# Two strictnesses on purpose: a class-index cell may carry dated provenance
# after its token (``MAINTAINER (re-derived 2026-09-05; was ADOPTER)``), so it
# is read by lead token; a row's own cell is a bare token and is matched
# exactly, because a row that needs prose beside its tag has a class to join.
_LEAD_TOKEN = re.compile(r"^\**([A-Z_]+)")
#: The ledger's own idiom for the victim of a row. A row that names an adopter
#: as its victim and is tagged MAINTAINER is contradicting itself; reported as
#: an advisory, never as drift -- the tag is a judgement the tool cannot make.
_NAMED_ADOPTER = re.compile(r"Named user:\*{0,2}\s*an adopter", re.I)
#: The population split beside the live total on line 6.
_HEADLINE_SPLIT = re.compile(
    r"^\*\*Live: \d+\*\* — (\d+) logic bugs · (\d+) hygiene · (\d+) operator actions"
)
#: The adopter figure on the line after it.
_HEADLINE_ADOPTER = re.compile(r"^\*\*(\d+)\*\* reach an adopter")
#: The separator the headline split is written with. Built from its code point
#: because the string it lands in is written INTO the ledger, not printed, and
#: the portability contract cannot tell the two apart (it is right to be strict:
#: every other string in this file does reach a terminal).
_MIDDOT = chr(0xB7)
#: A §2 population-table row: ``| LOGIC_BUG | 62 | code behaves wrongly |``
_POPULATION_TABLE_ROW = re.compile(
    r"^\|\s*(" + "|".join(POPULATIONS) + r")(?![A-Z_])\s*\|\s*(\d+)\s*\|"
)
#: A §2 audience-table row: ``| **ADOPTER** — someone who ... | **62** |``
_AUDIENCE_TABLE_ROW = re.compile(
    r"^\|\s*\**(" + "|".join(AUDIENCES) + r")(?![A-Z_])\**[^|]*\|\s*\**(\d+)\**\s*\|"
)


def member_cells(row: str) -> list[str]:
    """A member row's cells, split on UNESCAPED pipes only (``\\|`` is a
    literal pipe in this file)."""
    body = row.strip()
    return [c.strip() for c in re.split(r"(?<!\\)\|", body[1:-1])]


def declared_class_tags(text: str) -> dict[str, tuple[str | None, str | None]]:
    """``{'§C1': (population, audience)}`` from the §2 class table -- the lead
    token of each cell (``MAINTAINER (re-derived ...; was ADOPTER)`` reads as
    ``MAINTAINER``), or None for a placeholder."""
    out: dict[str, tuple[str | None, str | None]] = {}
    for ln in text.splitlines():
        m = _CLASS_TABLE_ROW.match(ln)
        if not m:
            continue
        cells = [c.strip() for c in ln.split("|")]
        pop = _LEAD_TOKEN.match(cells[4]) if len(cells) > 4 else None
        aud = _LEAD_TOKEN.match(cells[5]) if len(cells) > 5 else None
        out[m.group(1)] = (pop.group(1) if pop else None, aud.group(1) if aud else None)
    return out


def _section2_prelude(text: str) -> tuple[int, int]:
    """``(start, end)`` line indexes of §2's own prelude -- from its heading to
    the class index -- where the population and audience tables live."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if _SECTION2_HEADER.match(ln)), None)
    if start is None:
        return (0, 0)
    end = next(
        (j for j in range(start + 1, len(lines)) if lines[j].startswith("### Class index")),
        len(lines),
    )
    return (start, end)


def _is_struck(row: str) -> bool:
    """True when a member row carries the file's own closed marker."""
    return row.lstrip("| ").startswith("~~")


def ledger_sections(text: str) -> dict[str, list[str]]:
    """``{'§C1': [member row, ...]}`` for every class section in §2.

    Bounded by the ``### §CN`` headings themselves, so a class gains or loses
    rows without anyone maintaining a range.

    The LAST class section ends at the next ``##`` (h2), not at EOF. §C0 is last
    and the file continues into §3..§7 and Appendix B, whose id index is hundreds
    of ``| `DEF-N` |`` rows -- sweeping those in counted 627 "members" against a
    true 212 on the first cut of this parser. A section boundary that runs to EOF
    is not a boundary.
    """
    lines = text.splitlines()
    starts: list[tuple[int, str]] = [
        (i, m.group(1)) for i, ln in enumerate(lines) if (m := _SECTION_HEADING.match(ln))
    ]
    out: dict[str, list[str]] = {}
    for k, (idx, name) in enumerate(starts):
        if k + 1 < len(starts):
            end = starts[k + 1][0]
        else:
            end = next(
                (j for j in range(idx + 1, len(lines)) if lines[j].startswith("## ")),
                len(lines),
            )
        out[name] = [ln for ln in lines[idx:end] if _MEMBER_ROW.match(ln)]
    return out


def declared_class_table(text: str) -> dict[str, tuple[int | None, int | None]]:
    """``{'§C1': (declared_members, declared_live_or_None)}`` from the §2 table.

    Two cell shapes are in use: a bare total (``28``) and a total annotated with
    a split (``15 (**4 live**, 11 closed)``). Only the second declares a live
    count -- which is precisely why the bare form went unchecked for so long.

    A placeholder cell (``-``, ``TBD``, empty) is recorded as UNPARSEABLE, never
    skipped. Skipping dropped the whole class from every comparison, silently and
    permanently.
    """
    out: dict[str, tuple[int | None, int | None]] = {}
    for ln in text.splitlines():
        m = _CLASS_TABLE_ROW.match(ln)
        if not m:
            continue
        cells = [c.strip() for c in ln.split("|")]
        members_cell = cells[3] if len(cells) > 3 else ""
        total = re.match(r"^(\d+)", members_cell)
        if not total:
            out[m.group(1)] = (None, None)
            continue
        live = re.search(r"\*\*(\d+) live\*\*", members_cell)
        out[m.group(1)] = (int(total.group(1)), int(live.group(1)) if live else None)
    return out


def live_member_ids(text: str) -> set[str]:
    """Unstruck member-row ids across every ``§CN`` section -- the FIRST id of
    each row, as ``struck_member_ids`` always read it.

    A row's id cell may carry a second id (``| `DEF-536` `LG-1` | ...``: eight
    live rows on 2026-09-20). Until the 2026-09-20 cut this demanded a lone id
    before the pipe, so it returned 142 against ``derive()``'s 150 and those eight rows
    were invisible to the probe gate and to the Appendix B strike parity, which
    read them as "not live" and stayed silent over an index row struck above a
    live member.
    """
    out: set[str] = set()
    for rows in ledger_sections(text).values():
        for r in rows:
            if _is_struck(r):
                continue
            if m := _MEMBER_ID.match(r):
                out.add(m.group(2))
    return out


def struck_member_ids(text: str) -> set[str]:
    """Struck member-row ids across every ``§CN`` section."""
    out: set[str] = set()
    for rows in ledger_sections(text).values():
        for r in rows:
            if not _is_struck(r):
                continue
            if m := _MEMBER_ID.match(r):
                out.add(m.group(2))
    return out


def live_cell_ids(text: str) -> set[str]:
    """EVERY id carried by an unstruck member row across the ``§CN`` sections --
    the membership set, as against ``live_member_ids``'s counting set of first
    ids. A co-id owns its own Appendix B row and its own probe, so the gates
    that ask "does this id's index row agree" and "does this id's probe belong
    to a live row" ask about ids, not rows (both reviews of ``DEF-863``,
    2026-09-20: keyed on first ids, regions 5 and 6 and the row-hash gate were
    blind to nine live co-ids and their eight unstamped probes)."""
    out: set[str] = set()
    for rows in ledger_sections(text).values():
        for r in rows:
            if not _is_struck(r):
                out.update(cell_ids(r))
    return out


def struck_cell_ids(text: str) -> set[str]:
    """EVERY id carried by a struck member row across the ``§CN`` sections;
    the twin of ``live_cell_ids``."""
    out: set[str] = set()
    for rows in ledger_sections(text).values():
        for r in rows:
            if _is_struck(r):
                out.update(cell_ids(r))
    return out


def appendix_b_strike_state(text: str) -> dict[str, bool]:
    """``{id: is_struck}`` for every Appendix B index row.

    Appendix B is keyed by id and claims it "cannot drift" from the member rows.
    Nothing compared the two strike markers, so it could and did.
    """
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith("## Appendix B")), None)
    if start is None:
        return {}
    end = next(
        (j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")),
        len(lines),
    )
    out: dict[str, bool] = {}
    for ln in lines[start:end]:
        if m := _APPENDIX_B_ROW.match(ln):
            out[m.group(2)] = bool(m.group(1))
    return out


# --------------------------------------------------------------------------
# Derivations: what each region SHOULD say, computed from the member rows.
# --------------------------------------------------------------------------


def _cell(total: int, live: int, struck: int) -> str:
    """The class-index members cell, in the wording the file already uses.

    A class with no struck rows keeps the bare form; one with any keeps the
    ``N (**L live**, C closed)`` split that §C2 and §C6 established. The split
    is what the suite can check, so a class that has closures must carry it.
    """
    return f"{total} (**{live} live**, {struck} closed)" if struck else str(total)


def _class_cells(text: str) -> tuple[dict[str, int], dict[str, str]]:
    """``({class: 1-indexed line}, {class: current cell text})`` from the §2 table."""
    line_of: dict[str, int] = {}
    cell_of: dict[str, str] = {}
    for i, ln in enumerate(text.splitlines()):
        m = _CLASS_TABLE_ROW.match(ln)
        if not m:
            continue
        cells = ln.split("|")
        if len(cells) > 3:
            line_of[m.group(1)] = i + 1
            cell_of[m.group(1)] = cells[3]
    return line_of, cell_of


def derive(text: str) -> dict[str, object]:
    """Every derived quantity, computed once from the member rows.

    ``population_live`` / ``audience_live`` count every LIVE row exactly once
    under its class's tags, or its own when the class is MIXED.
    ``tag_problems`` is the closed-world arm: a live row whose tag is not in
    the vocabulary (a class-index placeholder, a MIXED-class row without its
    cells, a misspelt token) is named rather than dropped, so a count can
    never be right by omission.
    """
    sections = ledger_sections(text)
    live_total = sum(1 for rows in sections.values() for r in rows if not _is_struck(r))
    tags = declared_class_tags(text)
    pop_live = {p: 0 for p in POPULATIONS}
    aud_live = {a: 0 for a in AUDIENCES}
    pop_struck = {p: 0 for p in POPULATIONS}
    aud_struck = {a: 0 for a in AUDIENCES}
    problems: list[str] = []
    advisories: list[str] = []
    classes_with_live = 0
    standalone_live = 0
    for name, rows in sections.items():
        live_rows = [r for r in rows if not _is_struck(r)]
        struck_rows = [r for r in rows if _is_struck(r)]
        cpop, caud = tags.get(name, (None, None))
        if live_rows:
            # Deliberately the BOTH-axes test: a class MIXED on one axis still
            # has a shared unit of work, so it is a class, not a standalone
            # row-set. The row tool's sibling rule (ledger_row._mixed_tags) is
            # per-axis on purpose; do not widen this one to match it -- pinned
            # by test_a_class_mixed_on_one_axis_is_a_class_not_a_standalone.
            if (cpop, caud) == (MIXED, MIXED):
                standalone_live += len(live_rows)
            else:
                classes_with_live += 1
        for label, ctag, vocab, live_counter, struck_counter, cell in (
            ("population", cpop, POPULATIONS, pop_live, pop_struck, 4),
            ("audience", caud, AUDIENCES, aud_live, aud_struck, 5),
        ):
            if ctag in vocab:
                live_counter[ctag] += len(live_rows)
                struck_counter[ctag] += len(struck_rows)
                # THE CONTRADICTION ARM. A row carrying its own cell under a
                # class that declares a token is counted by the class and
                # printed by the row; flipping §C0's index cell from MIXED
                # moved the adopter figure 55 -> 80 with every gate green
                # (failure-mode pass + code review, 2026-09-08, both driven).
                for r in live_rows:
                    cells = member_cells(r)
                    # Only the full MIXED shape counts as "its own cells"; a
                    # malformed row (an unescaped pipe: five cells) is the row
                    # helper's refusal, not a classification.
                    if len(cells) >= 6 and cells[cell] != ctag:
                        rid = (_MEMBER_ID.match(r) or [None, None, "?"])[2]
                        problems.append(
                            f"{name} {rid}: carries its own {label} cell {cells[cell]!r} but "
                            f"the class index declares {ctag!r}, not MIXED -- the cell is not "
                            "counted; strip it or mark the class MIXED"
                        )
            elif ctag == MIXED:
                for r in live_rows:
                    cells = member_cells(r)
                    rid = (_MEMBER_ID.match(r) or [None, None, "?"])[2]
                    tok = cells[cell] if len(cells) > cell else None
                    if tok in vocab:
                        live_counter[tok] += 1
                    else:
                        problems.append(
                            f"{name} {rid}: {label} {tok!r} is not one of {vocab} -- a row "
                            "in a MIXED class carries its own `pop | aud` cells"
                        )
                for r in struck_rows:
                    # A closed row is not gated, so its cell is read the way a
                    # class cell is (lead token); ledger_trend reads the same.
                    cells = member_cells(r)
                    lead = _LEAD_TOKEN.match(cells[cell]) if len(cells) > cell else None
                    if lead and lead.group(1) in vocab:
                        struck_counter[lead.group(1)] += 1
            elif live_rows:
                problems.append(
                    f"{name}: class-index {label} {ctag!r} is not one of {vocab} or MIXED, "
                    f"and the class has {len(live_rows)} live row(s)"
                )
        # A tag is a judgement; the one contradiction the text itself can
        # witness is the file's own victim idiom against a MAINTAINER tag.
        for r in live_rows:
            cells = member_cells(r)
            aud = caud if caud in AUDIENCES else (cells[5] if len(cells) > 5 else None)
            if aud == "MAINTAINER" and _NAMED_ADOPTER.search(cells[2]):
                rid = (_MEMBER_ID.match(r) or [None, None, "?"])[2]
                advisories.append(
                    f"{name} {rid}: tagged MAINTAINER but its text names an adopter as the "
                    "user hurt -- re-tag it, or say why the maintainer is the victim"
                )
    return {
        "sections": {k: len(v) for k, v in sections.items()},
        "live_per_class": {
            k: sum(1 for r in v if not _is_struck(r)) for k, v in sections.items()
        },
        "struck_per_class": {
            k: sum(1 for r in v if _is_struck(r)) for k, v in sections.items()
        },
        "live_total": live_total,
        "class_count": len(sections),
        "classes_with_live": classes_with_live,
        "standalone_live": standalone_live,
        "population_live": pop_live,
        "audience_live": aud_live,
        "population_struck": pop_struck,
        "audience_struck": aud_struck,
        "tag_problems": problems,
        "tag_advisories": advisories,
    }


def _probe_ids() -> set[str]:
    """Ids carried by ``LEDGER_PROBES.json``, or an empty set when absent."""
    if not _PROBES.is_file():
        return set()
    try:
        doc = json.loads(_PROBES.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # strict decode: a structured answer (DEF-829)
        return set()
    return {p.get("id") for p in doc.get("probes", []) if p.get("id")}


def find_drift(text: str) -> list[dict[str, object]]:
    """Every region whose stated value disagrees with the member rows.

    Each entry carries ``region``, ``detail``, and -- where the repair is a
    literal substitution -- ``line`` (1-indexed), ``old`` and ``new``.
    """
    d = derive(text)
    lines = text.splitlines()
    drift: list[dict[str, object]] = []

    # 1. Top-of-file headline.
    for i, ln in enumerate(lines):
        if m := _HEADLINE.match(ln):
            stated = int(m.group(1))
            if stated != d["live_total"]:
                drift.append({
                    "region": "headline",
                    "line": i + 1,
                    "detail": f"headline says Live: {stated}; sections carry {d['live_total']}",
                    "old": m.group(0),
                    "new": f"**Live: {d['live_total']}**",
                })
            break

    # 2. §2 header: live total, classes with live rows, standalone live rows.
    for i, ln in enumerate(lines):
        if m := _SECTION2_HEADER.match(ln):
            stated = tuple(int(g) for g in m.groups())
            want = (d["live_total"], d["classes_with_live"], d["standalone_live"])
            if stated != want:
                drift.append({
                    "region": "section2-header",
                    "line": i + 1,
                    "detail": (f"section-2 header says {stated[0]} LIVE in {stated[1]} classes + "
                               f"{stated[2]} standalone; sections carry {want}"),
                    "old": f"({stated[0]} LIVE issues in {stated[1]} classes + {stated[2]} standalone)",
                    "new": f"({want[0]} LIVE issues in {want[1]} classes + {want[2]} standalone)",
                })
            break

    # 3. Class-index member counts and live splits.
    declared = declared_class_table(text)
    cell_line, cell_text = _class_cells(text)
    for name, (total, live) in sorted(declared.items()):
        actual_total = d["sections"].get(name)
        actual_live = d["live_per_class"].get(name)
        struck = d["struck_per_class"].get(name, 0)
        if actual_total is None:
            continue
        if total is None:
            drift.append({
                "region": "class-index-count",
                "detail": f"{name}: member cell is a placeholder; section carries {actual_total}",
            })
            continue
        if total != actual_total:
            drift.append({
                "region": "class-index-count",
                "detail": f"{name}: cell says {total} members; section carries {actual_total}",
                "line": cell_line.get(name),
                "old": cell_text.get(name, ""),
                "new": _cell(actual_total, actual_live, struck),
            })
        if live is None and struck:
            # THE GAP THAT HID §C3. A bare cell declares no live count, so the
            # existing suite skipped it entirely -- a class could be wholly
            # closed and still read as live work.
            drift.append({
                "region": "class-index-live-split",
                "detail": (
                    f"{name}: cell is a bare number but {struck} member(s) are struck; "
                    f"it must declare ({actual_live} live, {struck} closed)"
                ),
                "line": cell_line.get(name),
                "old": cell_text.get(name, ""),
                "new": _cell(actual_total, actual_live, struck),
            })
        elif live is not None and live != actual_live:
            drift.append({
                "region": "class-index-live-split",
                "detail": f"{name}: cell declares {live} live; section carries {actual_live}",
                "line": cell_line.get(name),
                "old": cell_text.get(name, ""),
                "new": _cell(actual_total, actual_live, struck),
            })

    # 4. Inline `**Members (N)**` lines.
    cur: str | None = None
    for i, ln in enumerate(lines):
        if m := _SECTION_HEADING.match(ln):
            cur = m.group(1)
        elif ln.startswith("## "):
            cur = None
        if cur and (m := _MEMBERS_LINE.match(ln)):
            stated = int(m.group(1))
            actual = d["sections"].get(cur, 0)
            if stated != actual:
                drift.append({
                    "region": "members-line",
                    "line": i + 1,
                    "detail": f"{cur}: `Members ({stated})` against {actual} member rows",
                    "old": f"**Members ({stated})**",
                    "new": f"**Members ({actual})**",
                })

    # 5. Appendix B strike parity -- per ID, not per row: a co-id has its own
    #    index row (`DEF-863`; keyed on first ids this was blind to a co-id's
    #    index row struck over a live member, and the reverse).
    struck_ids = struck_cell_ids(text)
    live_ids = live_cell_ids(text)
    for ident, indexed_struck in sorted(appendix_b_strike_state(text).items()):
        section_struck = ident in struck_ids
        if section_struck and not indexed_struck:
            drift.append({
                "region": "appendix-b-strike",
                "detail": f"{ident}: struck in its class section, unstruck in Appendix B",
            })
        elif indexed_struck and ident in live_ids:
            drift.append({
                "region": "appendix-b-strike",
                "detail": f"{ident}: struck in Appendix B, live in its class section",
            })

    # 6. Probe roster: a struck row must not keep a probe -- on ANY of its ids
    #    (a co-id's orphan probe used to surface only as a STRIKE_CANDIDATE in
    #    check_ledger_probes; its retired filter now reads the whole cell, so
    #    this region is the one place that reports it).
    stale_probes = sorted(_probe_ids() & struck_ids)
    for ident in stale_probes:
        drift.append({
            "region": "probe-roster",
            "detail": f"{ident}: struck in its class section but still carries a probe",
        })

    # 7. The headline's population split and adopter figure (lines 6-7). A
    #    line the regex cannot find is reported, not skipped: a reworded
    #    headline would otherwise carry a typed number nothing re-derives,
    #    which is the very defect this region closes.
    pop, aud = d["population_live"], d["audience_live"]
    if not any(_HEADLINE_SPLIT.match(ln) for ln in lines):
        drift.append({"region": "headline-shape",
                      "detail": "no headline split line (`**Live: N** -- N logic bugs "
                                "<middle dot> N hygiene <middle dot> N operator actions.`) found; "
                                "a reworded line carries a typed number nothing re-derives"})
    if not any(_HEADLINE_ADOPTER.match(ln) for ln in lines):
        drift.append({"region": "headline-shape",
                      "detail": "no headline adopter line (`**N** reach an adopter.`) found"})
    for i, ln in enumerate(lines):
        if m := _HEADLINE_SPLIT.match(ln):
            stated = tuple(int(g) for g in m.groups())
            want = (pop["LOGIC_BUG"], pop["HYGIENE"], pop["OPERATOR_ACTION"])
            if stated != want:
                def _split(t: tuple[int, int, int]) -> str:
                    return (f"{t[0]} logic bugs {_MIDDOT} {t[1]} hygiene {_MIDDOT} "
                            f"{t[2]} operator actions")
                drift.append({
                    "region": "headline-split",
                    "line": i + 1,
                    "detail": f"headline splits the live total as {stated}; rows carry {want}",
                    "old": _split(stated),
                    "new": _split(want),
                })
            break
    for i, ln in enumerate(lines):
        if m := _HEADLINE_ADOPTER.match(ln):
            stated = int(m.group(1))
            if stated != aud["ADOPTER"]:
                drift.append({
                    "region": "headline-adopter",
                    "line": i + 1,
                    "detail": f"headline says {stated} reach an adopter; rows carry {aud['ADOPTER']}",
                    "old": f"**{stated}** reach an adopter",
                    "new": f"**{aud['ADOPTER']}** reach an adopter",
                })
            break

    # 8. §2's population and audience tables -- one row per vocabulary token,
    #    each row's number derived. A token with no row is the closed-world
    #    gap (a population nobody counts), reported under `vocabulary`.
    start, end = _section2_prelude(text)
    seen_pop: set[str] = set()
    seen_aud: set[str] = set()
    for i in range(start, end):
        ln = lines[i]
        if m := _POPULATION_TABLE_ROW.match(ln):
            tok, stated = m.group(1), int(m.group(2))
            seen_pop.add(tok)
            if stated != pop[tok]:
                drift.append({
                    "region": "population-table",
                    "line": i + 1,
                    "detail": f"population table says {tok} = {stated}; rows carry {pop[tok]}",
                    "old": m.group(0),
                    "new": f"| {tok} | {pop[tok]} |",
                })
        elif m := _AUDIENCE_TABLE_ROW.match(ln):
            tok, stated = m.group(1), int(m.group(2))
            seen_aud.add(tok)
            if stated != aud[tok]:
                whole = m.group(0)
                a, b = m.start(2) - m.start(0), m.end(2) - m.start(0)
                drift.append({
                    "region": "audience-table",
                    "line": i + 1,
                    "detail": f"audience table says {tok} = {stated}; rows carry {aud[tok]}",
                    "old": whole,
                    "new": whole[:a] + str(aud[tok]) + whole[b:],
                })
    for tok in POPULATIONS:
        if tok not in seen_pop:
            drift.append({"region": "vocabulary",
                          "detail": f"section 2's population table has no row for {tok}"})
    for tok in AUDIENCES:
        if tok not in seen_aud:
            drift.append({"region": "vocabulary",
                          "detail": f"section 2's audience table has no row for {tok}"})

    # 9. The closed-world arm: every live row resolved to a token, or it is named.
    for problem in d["tag_problems"]:
        drift.append({"region": "vocabulary", "detail": problem})

    return drift


# --------------------------------------------------------------------------
# Repair
# --------------------------------------------------------------------------


def _atomic_write(path: Path, text: str) -> None:
    """Write through a sibling temp file and ``os.replace`` so a crash mid-write
    leaves the old file whole, never a truncated one. The ledger was gitignored
    until 2026-09-21: a torn write had no ``git checkout`` behind it, only the
    record branch's last handoff snapshot (failure-mode pass, 2026-09-08); the
    probes sidecar, written by ``ledger_row.py`` through its own atomic path,
    had the same exposure. Shared with
    ``ledger_row.py``, which loads this module for its grammar already."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

#: Regions ``--write`` can repair by literal substitution. The others name a
#: judgement call -- which cell wording to use, which probe to retire -- and a
#: generator that guessed at those would be inventing content, not deriving it.
#: The anti-vacuity floors ``main`` and the completeness contract hold the live
#: file to: a parse that finds fewer than this has broken, and "no drift" over
#: it would be a false green. They are COLLAPSE guards, not targets -- a parser
#: collapse reads near zero, an honest drain reads as a smaller ledger, and a
#: floor within reach of the live count reds on the drain (the ADOPTER floor
#: crossed three times in 2026-09 and moved by hand each time; the 2026-09-20
#: rebuild left exactly 150 member rows under a floor of 150). So each is HALF
#: of a dated figure ``derive()`` read from the pre-rebuild record file
#: (``task-packs/FORWARD_LEDGER_PRE_REBUILD_2026-09-20.md``, record branch);
#: ``tests/test_generate_ledger_regions.py`` re-derives the dict from that file
#: whenever it is present and pins each floor at or below half. Re-derive at
#: the next rebuild only -- never by hand between them, never upward. The tag
#: floors sit on the tag each axis carries most, so a vocabulary rename or a
#: cell shift reads as zero there while the row total stays put. Module-level
#: so a synthetic test can lower them.
_SNAPSHOT_2026_09_20 = {"live": 149, "sections": 53, "HYGIENE": 104, "MAINTAINER": 141}
#: The section floor sits on the same snapshot: the 2026-09-20 cut removed
#: twenty class sections in one act (53 -> 33), so a hand literal here was a
#: target one more such act away -- and this one refuses the whole run.
_FLOOR_SECTIONS = _SNAPSHOT_2026_09_20["sections"] // 2
_FLOOR_ROWS = _SNAPSHOT_2026_09_20["live"] // 2
_FLOOR_POPULATION = ("HYGIENE", _SNAPSHOT_2026_09_20["HYGIENE"] // 2)
_FLOOR_AUDIENCE = ("MAINTAINER", _SNAPSHOT_2026_09_20["MAINTAINER"] // 2)

_WRITABLE = {"headline", "section2-header", "members-line",
             "class-index-count", "class-index-live-split",
             "headline-split", "headline-adopter", "population-table", "audience-table"}


def apply_writable(text: str, drift: list[dict[str, object]]) -> tuple[str, int]:
    """Apply every literal-substitution repair. Returns (text, count).

    Substitutions are applied by CONTENT ANCHOR on the identified line, never by
    replaying a line number into a rewritten buffer -- the ledger's own editing
    rules say so, and line numbers shift as earlier repairs land.
    """
    lines = text.splitlines(keepends=True)
    applied = 0
    for entry in drift:
        if entry["region"] not in _WRITABLE:
            continue
        idx = entry.get("line")
        old, new = entry.get("old"), entry.get("new")
        if not (isinstance(idx, int) and isinstance(old, str) and isinstance(new, str)):
            continue
        i = idx - 1
        if not (0 <= i < len(lines)):
            continue
        if entry["region"].startswith("class-index"):
            # ⚠ POSITIONAL, never textual. A class cell holds a bare number, and
            # that number also appears in the row's own anchor -- `[§C14](#c14--...)`.
            # A `str.replace` of the cell VALUE rewrote the LABEL to `§C15` on the
            # second pass, silently deleting a class from the index. Splitting on
            # the delimiter and assigning by position cannot reach the anchor.
            cells = lines[i].rstrip("\n").split("|")
            if len(cells) > 3:
                cells[3] = f" {new.strip()} "
                lines[i] = "|".join(cells) + "\n"
                applied += 1
            continue
        if old in lines[i]:
            lines[i] = lines[i].replace(old, new, 1)
            applied += 1
    return "".join(lines), applied


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="report drift without writing; exit 1 when any is found")
    ap.add_argument("--write", action="store_true",
                    help="repair the literal-substitution regions in place")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    if args.check and args.write:
        print("--check and --write are mutually exclusive", file=sys.stderr)
        return 2

    if not _LEDGER.is_file():
        # Self-host only. An adopter tree has no task-packs/.
        msg = f"no ledger at {_LEDGER.name} -- self-host only; nothing to do"
        print(json.dumps({"status": "absent", "note": msg}) if args.json else msg)
        return 0

    try:
        text = _LEDGER.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:  # strict decode: a structured answer (DEF-829)
        # Fail CLOSED and LOUD. An unreadable ledger must never report "no
        # drift" -- that is a clean green over a file nobody parsed.
        print(f"cannot read {_LEDGER.name}: {exc}", file=sys.stderr)
        print("refusing to report -- an unparseable ledger is not an honest null",
              file=sys.stderr)
        return 1

    sections = ledger_sections(text)
    if len(sections) < _FLOOR_SECTIONS or sum(len(v) for v in sections.values()) < _FLOOR_ROWS:
        # The same floor the test module keeps, for the same reason: a broken
        # matcher would report zero drift over a file it failed to parse.
        print(f"parsed {len(sections)} class sections and "
              f"{sum(len(v) for v in sections.values())} member rows, which cannot be right "
              "-- the matcher has broken and every check below would pass vacuously",
              file=sys.stderr)
        return 1

    drift = find_drift(text)

    if args.write and drift:
        new_text, applied = apply_writable(text, drift)
        if applied:
            _atomic_write(_LEDGER, new_text)
        remaining = [d for d in drift if d["region"] not in _WRITABLE]
        if args.json:
            print(json.dumps({"applied": applied, "remaining": remaining}, indent=2))
        else:
            print(f"applied {applied} literal repair(s)")
            for d in remaining:
                print(f"  MANUAL  [{d['region']}] {d['detail']}")
        # A judgement region left over is not a converged ledger. The first cut
        # returned 0 here, so `--write; echo $?` read as done while the MANUAL
        # lines scrolled past (failure-mode pass, 2026-09-08).
        return 1 if remaining else 0

    derived = derive(text)
    if args.json:
        print(json.dumps({"drift": drift, "derived": derived}, indent=2))
    else:
        if not drift:
            print(f"ledger regions converged ({derived['live_total']} live rows)")
        else:
            print(f"{len(drift)} region(s) disagree with the member rows:")
            for d in drift:
                print(f"  [{d['region']}] {d['detail']}")
        for a in derived["tag_advisories"]:
            print(f"  ADVISORY {a}")
    return 1 if (drift and args.check) else 0


if __name__ == "__main__":
    raise SystemExit(main())
