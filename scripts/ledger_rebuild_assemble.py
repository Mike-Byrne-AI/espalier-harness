#!/usr/bin/env python3
"""Assemble the rebuilt forward ledger from the rebuild workflow's lane verdicts.

Why this exists
---------------
The third rebuild of ``task-packs/FORWARD_LEDGER.md`` (the ledger-ships pack,
its rebuild stage) turns roughly one hundred and fifty agent verdicts into one
rewritten 1.4 MB file. That rewrite is a script's job, not an agent's: it has
to parse identically under ``scripts/generate_ledger_regions.py`` afterwards,
it has to be byte-for-byte reproducible from the same verdicts, and the ledger
row that owns the rebuild says the cut must be re-runnable at seed time because
rows land daily. So the workflow
(``.claude/workflows/_ledger_rebuild_2026_09_20.js``) adjudicates and this
script assembles; nothing in the workflow writes the ledger by hand.

What it reads
-------------
* ``--ledger`` / ``--probes``: the STAGED ledger and probes file (a scratch
  clone's copies, never the live tree's -- the live write is 1-D's). A probes
  file whose ``_count`` disagrees with its rows is refused, as the row verbs
  refuse it: that mismatch is the hand edit's only trace.
* ``--final``: ``verdicts.final.json``, the workflow's merged, clamped verdict
  list -- one entry per id: ``verdict`` (keep / strike / fold / unresolved),
  ``severity`` (already clamped: never lower than the row's), the final
  ``population`` / ``audience`` labels (vocabulary tokens or null), ``fold_into``.
* ``--lanes``: the directory of lane JSONs. Only files carrying ``verdicts``
  are read, and only for each keep's rewritten ``row`` (``anchor``, ``body``)
  and each strike's ``strike_evidence``. Decisions come from ``--final``,
  never from a lane file: a lane's own verdict may have been downgraded.

What it writes (all under ``--out``, through the generator's atomic writer,
all four or none; no input is rewritten in place; an ``--out`` that already
holds a rebuild is refused without ``--force``, because a second run over an
already-cut ledger would otherwise replace the record payload with an empty one)
-------------------------------------------------------------------------
* ``FORWARD_LEDGER.rebuilt.md`` -- the ledger with every §2 member row
  resolved: a keep is rewritten to the lane's text (its id cell re-emitted
  verbatim, so a row carrying a second id keeps it; its Appendix B row's site
  cell follows the new anchor, as the filing verb keeps them in step); a
  strike or a fold is DELETED from its section and every id it carried gets
  the same ``~~`` tombstone in Appendix B that ``scripts/ledger_row.py strike``
  writes (so the generator's parity region stays silent and a citation still
  finds the id); a fold also gains an Appendix A4 row naming the owner. A row
  is left byte-for-byte as it was, and named in the report, when it is
  unresolved, has no verdict, is a keep whose lane text is missing, whose
  severity would be LOWER than the row's or whose severity cell cannot be
  read, or a fold into a row that leaves. Previously struck rows (``~~``)
  are RETAINED by default -- the structural cut is 1-D's decision; pass
  ``--drop-previously-struck`` there to move them to the record payload.
  The derived regions are then regenerated with the generator's own
  ``find_drift`` / ``apply_writable``.
* ``LEDGER_PROBES.rebuilt.json`` -- the probes minus every struck or folded
  id, ``_count`` re-derived, the way the strike verb retires a probe.
* ``struck-rows.md`` -- the record-branch payload: every removed row
  verbatim, with the evidence the lane cited.
* ``assemble-report.json`` -- the counts, every held row by id and reason,
  the per-class tag decisions, and any drift the generator could not repair;
  plus two routing reports a shared id leaves, both counted in the headline
  and neither a hold: ``co_id_extra_verdicts`` (a co-id's extra-section
  verdict that was the twin row's, not the member row's) and
  ``extra_rows_citing_retired_ids`` (a row outside the class sections that
  stays while an id it carries was retired above -- the strike verb's own
  precedent, ``DEF-538``+``LG-5``, and the structural cut's decision).

Which row a verdict is about
----------------------------
Six §1 launch-gate rows carry the same id pair as a §2 member row; four of
those member rows are live today. The workflow's census keys every LIVE
member row by its first id, and the extra-sections lane gets every other
unstruck id in §1 / §3 / §4 / §5 -- so a twin reaches that lane under the
co-id, and every extra-lane verdict is written ``section: extra``. Hence:

* a verdict on a live row's first id is that row's, and its section must be
  a class section (``§C1`` / ``C1``): one that says ``extra`` disclaims the
  row it would land on and is HELD (``section_disclaims_row``);
* a verdict on a co-id is the member row's only when its section is a class
  section; with ``extra`` it is the twin's, reported and never applied --
  and if no row outside the class sections carries that id, the report
  would be untrue, so that is held as a conflict instead;
* in the extra pass, a verdict is an extra row's when its id is not a live
  census key and its section is not a class section; a struck member row's
  first id is legitimately the extra lane's (``DEF-538`` today);
* a row outside the class sections that carries two ids is struck both or
  neither: every other id needs a strike of its own, or a member row that
  leaves in the same run. A twin therefore leaves only with its member row.

The first run held four kept rows as conflicts before this rule existed.

Held rows are a refusal, not a footnote: a run whose held count exceeds
``--max-held`` (default 0) writes nothing and exits 3 naming the ids. A
rebuild in which some rows silently kept their old text would otherwise be
indistinguishable, by its outputs, from one that rewrote every row.

Class tags, per axis
--------------------
A classed row inherits its population and its audience from the §2
class-index row; on an axis the index marks MIXED the row carries its own
cell (four classes are MIXED on one axis today, and their rows carry six
cells). Each axis is decided on its own: when the final labels of a class's
live rows all agree on a token that differs from the index, that cell is
rewritten (``TOKEN (re-derived <date>; was OLD)`` -- the generator reads the
lead token); when they disagree, that axis becomes MIXED and every live row in
the class gets its own cells. A class whose index carries a placeholder on an
axis has its keeps refused rather than guessed. Nothing else in the file is
restructured here: sections leaving the working file, the two floors and the
live write are 1-D's.

Usage
-----
    python scripts/ledger_rebuild_assemble.py --ledger <clone>/task-packs/FORWARD_LEDGER.md \\
        --probes <clone>/task-packs/LEDGER_PROBES.json --lanes <out>/lanes \\
        --final <out>/verdicts.final.json --out <out> --date 2026-09-20

Exit 0 when the outputs were written; 3 when the run was refused (held rows
above ``--max-held``, or an ``--out`` that already holds a rebuild); 2 on an
unreadable or malformed input; 1 when the ledger parses to no class sections
at all (not a ledger -- refusing is safer than an empty rebuild).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load(name: str):
    """A sibling script as a module (``scripts/`` is not a package). An
    already-imported copy is reused rather than re-executed under it, the
    way ``scripts/ledger_trend.py`` does: a second module object for the same
    file would make a monkeypatch land on whichever copy a test bound."""
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, "__file__", None):
        return existing
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_GEN = _load("generate_ledger_regions")  # the grammar's one home

VERDICTS = ("keep", "strike", "fold", "unresolved")
OUTPUT_NAMES = ("FORWARD_LEDGER.rebuilt.md", "LEDGER_PROBES.rebuilt.json",
                "struck-rows.md", "assemble-report.json")
_RANK = {"blocker": 0, "major": 1, "minor": 2, "nit": 3}
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_LEAD = re.compile(r"^\**([a-z]+)")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: Every backticked id in a cell, in order.
_IDS_IN_CELL = re.compile(r"`([^`]+)`")
#: A cell made only of backticked ids (struck or not) and whitespace -- the
#: id-cell shape of the §1 / §3 / §4 / §5 rows.
_ID_LIST_CELL = re.compile(r"^(?:\s*(?:~~)?`[^`]+`(?:~~)?)+\s*$")
#: A verdict's ``section`` when it is about a §2 member row. The adjudicator
#: lanes write ``§C1`` and ``C1`` both (measured on the first run: 11 ``C0``
#: beside 30 ``§C0``); the extra-sections lane's verdicts carry ``extra``.
_CLASS_SECTION = re.compile(r"^§?C\d+$")


def _is_class_section(section: object) -> bool:
    return bool(_CLASS_SECTION.match(str(section or "").strip()))


_HELD_KEYS = ("unresolved", "no_verdict", "keep_without_text", "severity_refused",
              "severity_unreadable", "row_refused", "fold_refused", "extra_unresolved",
              "conflicting_verdicts", "section_disclaims_row")


class Refused(Exception):
    """A row this script will not write; the caller records why."""


@dataclass
class Row:
    id: str
    ids: list[str]
    id_cell: str
    section: str
    idx: int
    line: str
    struck: bool
    cells: list[str]


@dataclass
class Result:
    text: str
    probes: dict
    struck_md: str
    report: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# Cells and rows
# --------------------------------------------------------------------------
def escape_cell(value: str) -> str:
    """One line, single-spaced, every unescaped pipe written ``\\|`` (the
    ledger's cell grammar: ``generate_ledger_regions.member_cells`` splits on
    unescaped pipes only, and a bare pipe silently adds a cell)."""
    flat = " ".join(str(value).split())
    return _UNESCAPED_PIPE.sub(r"\\|", flat)


def build_row(id_cell: str, anchor: str, body: str, severity: str,
              tags: tuple[str, str] | None) -> str:
    """A member row in the file's grammar, re-parsed before it is returned.
    ``id_cell`` is the row's first cell VERBATIM (it may carry a second id)."""
    if severity not in _RANK:
        raise Refused(f"{id_cell}: severity {severity!r} is not one of {sorted(_RANK)}")
    cells = [id_cell.strip(), escape_cell(anchor), escape_cell(body), severity]
    if tags is not None:
        pop, aud = tags
        if pop not in _GEN.POPULATIONS or aud not in _GEN.AUDIENCES:
            raise Refused(f"{id_cell}: tags {tags!r} are not a (population, audience) pair")
        cells += [pop, aud]
    if not cells[1] or not cells[2]:
        raise Refused(f"{id_cell}: an empty anchor or body cell")
    line = "| " + " | ".join(cells) + " |"
    want = 6 if tags is not None else 4
    got = len(_GEN.member_cells(line))
    if got != want or not _GEN._MEMBER_ROW.match(line) or _GEN._is_struck(line):
        raise Refused(f"{id_cell}: the rebuilt row parses to {got} cells, not {want}")
    return line


def _severity_of(cells: list[str]) -> str | None:
    if len(cells) < 4:
        return None
    m = _LEAD.match(cells[3].strip())
    return m.group(1) if m and m.group(1) in _RANK else None


def _own_tags(cells: list[str]) -> tuple[str | None, str | None]:
    """A row's own ``pop | aud`` cells when it carries six, else (None, None)."""
    if len(cells) >= 6:
        return (cells[4] if cells[4] in _GEN.POPULATIONS else None,
                cells[5] if cells[5] in _GEN.AUDIENCES else None)
    return (None, None)


# --------------------------------------------------------------------------
# Scanning the file (line-indexed twins of the generator's parsers)
# --------------------------------------------------------------------------
def section_ranges(lines: list[str]) -> list[tuple[str, int, int]]:
    """``[(§CN, start, end)]`` with the generator's own boundary rule: a class
    section ends at the next ``### §C`` heading, the last one at the next h2."""
    starts = [(i, m.group(1)) for i, ln in enumerate(lines)
              if (m := _GEN._SECTION_HEADING.match(ln))]
    out: list[tuple[str, int, int]] = []
    for k, (idx, name) in enumerate(starts):
        if k + 1 < len(starts):
            end = starts[k + 1][0]
        else:
            end = next((j for j in range(idx + 1, len(lines)) if lines[j].startswith("## ")),
                       len(lines))
        out.append((name, idx, end))
    return out


def scan_member_rows(lines: list[str]) -> list[Row]:
    rows: list[Row] = []
    for name, start, end in section_ranges(lines):
        for j in range(start, end):
            ln = lines[j]
            if _GEN._MEMBER_ROW.match(ln):
                cells = _GEN.member_cells(ln)
                ids = _IDS_IN_CELL.findall(cells[0]) if cells else []
                first = (_GEN._MEMBER_ID.match(ln) or [None, None, ""])[2]
                rows.append(Row(first, ids or [first], cells[0] if cells else f"`{first}`",
                                name, j, ln, _GEN._is_struck(ln), cells))
    return rows


def _heading_index(lines: list[str], prefix: str) -> int | None:
    for i, ln in enumerate(lines):
        if ln.startswith(prefix):
            return i
    return None


def scan_index_rows(lines: list[str]) -> dict[str, int]:
    """``{id: line index}`` of Appendix B rows, read only after its heading so a
    member row whose site cell happens to read ``§CN`` is never mistaken."""
    start = _heading_index(lines, "## Appendix B")
    if start is None:
        return {}
    out: dict[str, int] = {}
    for j in range(start, len(lines)):
        m = _GEN._APPENDIX_B_ROW.match(lines[j])
        if m and m.group(2) not in out:
            out[m.group(2)] = j
    return out


def scan_class_rows(lines: list[str]) -> dict[str, int]:
    return {m.group(1): i for i, ln in enumerate(lines)
            if (m := _GEN._CLASS_TABLE_ROW.match(ln))}


def _tombstone_index(line: str, rid: str) -> str:
    """The strike verb's own index tombstone: the id wrapped in ``~~``."""
    if "~~" in line.split("|")[1]:
        return line
    return line.replace(f"`{rid}`", f"~~`{rid}`~~", 1)


def _index_with_anchor(line: str, anchor: str) -> str:
    """The Appendix B row with its site cell (the third) following a keep's
    new anchor, positionally on unescaped pipes."""
    cells = _UNESCAPED_PIPE.split(line)
    if len(cells) <= 3:
        return line
    cells[3] = f" {escape_cell(anchor)} "
    return "|".join(cells)


def _class_cells_rewritten(line: str, pop: str | None, aud: str | None) -> str:
    """Positional, never textual (the generator's own rule for this row: a cell
    value can also appear inside the row's anchor). ``None`` leaves that cell
    as it is. Split on unescaped pipes; the rejoin is lossless."""
    cells = _UNESCAPED_PIPE.split(line)
    if len(cells) <= 5:
        raise Refused(f"class-index row has {len(cells)} cells; cannot rewrite tags")
    if pop is not None:
        cells[4] = f" {pop} "
    if aud is not None:
        cells[5] = f" {aud} "
    return "|".join(cells)


def find_extra_row(lines: list[str], rid: str, exclude: set[int], stop: int) -> tuple[int, list[str]] | None:
    """The unique table row OUTSIDE the class sections and BEFORE the
    appendices whose first or second cell is a list of backticked ids that
    holds ``rid`` unstruck (§1 rows are numbered and may carry two ids; §3-§5
    rows lead with the id). Returns ``(line index, every id in that cell)``;
    ambiguity or absence returns None and the caller reports it."""
    hits: list[tuple[int, list[str]]] = []
    for j in range(min(stop, len(lines))):
        ln = lines[j]
        if j in exclude or not ln.startswith("|"):
            continue
        body = ln.strip()
        cells = [c.strip() for c in _UNESCAPED_PIPE.split(body[1:-1] if body.endswith("|") else body[1:])]
        for c in cells[:2]:
            if not _ID_LIST_CELL.match(c):
                continue
            ids = _IDS_IN_CELL.findall(c)
            if rid in ids and f"~~`{rid}`~~" not in c:
                hits.append((j, ids))
                break
    return hits[0] if len(hits) == 1 else None


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------
def load_final(doc: object) -> list[dict]:
    """The merged verdict list, validated: a list, or an object holding one
    under ``verdicts`` / ``final``."""
    items = doc
    if isinstance(doc, dict):
        items = doc.get("verdicts", doc.get("final"))
    if not isinstance(items, list):
        raise ValueError("verdicts.final.json must be a list (or an object with a `verdicts` list)")
    out: list[dict] = []
    seen: set[str] = set()
    for i, e in enumerate(items):
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not e["id"]:
            raise ValueError(f"final[{i}]: no string `id`")
        if e["id"] in seen:
            raise ValueError(f"final: duplicate id {e['id']}")
        seen.add(e["id"])
        if e.get("verdict") not in VERDICTS:
            raise ValueError(f"final[{i}] {e['id']}: verdict {e.get('verdict')!r} is not one of {VERDICTS}")
        sec = e.get("section")
        if not (sec == "extra" or _is_class_section(sec)):  # decision-relevant since the twin routing
            raise ValueError(f"final[{i}] {e['id']}: section {sec!r} is neither a class section (§C1 / C1) nor 'extra'")
        sev = e.get("severity")
        if sev is not None and sev not in _RANK:
            raise ValueError(f"final[{i}] {e['id']}: severity {sev!r}")
        for key, vocab in (("population", _GEN.POPULATIONS), ("audience", _GEN.AUDIENCES)):
            val = e.get(key)
            if val is not None and val not in vocab:
                raise ValueError(f"final[{i}] {e['id']}: {key} {val!r} is not one of {vocab}")
        out.append(e)
    return out


def load_probes(doc: object, name: str = "probes") -> dict:
    """A probes document whose ``_count`` agrees with its rows; the disagreement
    is refused the way ``ledger_row.py`` refuses it (a hand edit's only trace)."""
    if not isinstance(doc, dict) or not isinstance(doc.get("probes"), list):
        raise ValueError(f"{name}: not a probes file (no `probes` list)")
    declared = doc.get("_count")
    if declared is not None and declared != len(doc["probes"]):
        raise ValueError(f"{name}: declares _count={declared} but carries {len(doc['probes'])} probes "
                         "-- a hand edit; reconcile the staged file before assembling")
    return doc


def load_lane_rows(lanes_dir: Path) -> tuple[dict[str, dict], list[str]]:
    """``{id: {anchor, body, lane, strike_evidence, notes}}`` from every lane
    file that carries ``verdicts``. On a duplicate id the first entry that
    carries a rewritten row wins (a row-less earlier entry must not shadow a
    later lane's text); every duplicate is reported. Files without
    ``verdicts`` (the census, the re-classifiers, the critic) are skipped."""
    rows: dict[str, dict] = {}
    duplicates: list[str] = []
    for path in sorted(lanes_dir.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:  # strict decode: a structured answer
            raise ValueError(f"{path.name}: {exc}") from exc
        if not isinstance(doc, dict) or not isinstance(doc.get("verdicts"), list):
            continue
        for v in doc["verdicts"]:
            if not isinstance(v, dict) or not isinstance(v.get("id"), str):
                continue
            rid = v["id"]
            row = v.get("row") if isinstance(v.get("row"), dict) else {}
            entry = {
                "anchor": row.get("anchor"), "body": row.get("body"), "lane": path.stem,
                "strike_evidence": v.get("strike_evidence") if isinstance(v.get("strike_evidence"), dict) else None,
                "notes": v.get("notes") or "",
            }
            prior = rows.get(rid)
            if prior is None:
                rows[rid] = entry
                continue
            has_text = bool(entry["anchor"] and entry["body"])
            prior_has = bool(prior["anchor"] and prior["body"])
            if has_text and not prior_has:
                duplicates.append(f"{rid} ({path.stem} kept -- it carries the row; {prior['lane']} did not)")
                rows[rid] = entry
            else:
                duplicates.append(f"{rid} ({prior['lane']} kept; {path.stem} ignored)")
    return rows, duplicates


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------
def _struck_entry(kind: str, r: Row, d: dict | None, lane: dict | None) -> str:
    ev = (lane or {}).get("strike_evidence") or {}
    parts = [f"### {r.id_cell} -- {r.section} -- {kind}"]
    if d is not None:
        parts.append(f"Verdict from lane `{d.get('lane', '?')}`; probe {d.get('probe', 'NOT_RUN')}.")
    if ev:
        parts.append("Evidence (the command as the lane recorded it, then what it printed, then why):")
        parts.append("")
        parts.append("```")
        parts.append(" ".join(str(ev.get("driven_command", "")).split()))
        parts.append(" ".join(str(ev.get("output_quoted", "")).split()))
        parts.append(" ".join(str(ev.get("reason", "")).split()))
        parts.append("```")
    if d is not None and d.get("fold_into"):
        parts.append(f"Folded into `{d['fold_into']}`.")
    parts.append("")
    parts.append("```")
    parts.append(r.line)
    parts.append("```")
    parts.append("")
    return "\n".join(parts)


def _lane_entry(lane_rows: dict[str, dict], ids: list[str], field: str) -> dict | None:
    """The first lane entry, in the order given (the deciding id, then the
    row's ids), that carries ``field`` -- so an entry that exists but is empty
    under one id never shadows the text or evidence filed under another."""
    for x in ids:
        e = lane_rows.get(x)
        if e and e.get(field):
            return e
    return next((lane_rows[x] for x in ids if x in lane_rows), None)


def _decision_for(r: Row, decisions: dict[str, dict],
                  has_extra_row: Callable[[str], bool]) -> tuple[dict | None, tuple[str, str] | None, list[str]]:
    """``(the member row's verdict, the hold as (report key, note), routing notes)``.

    The census keys a LIVE member row by its first id, so a verdict on that
    id is the row's -- when its section says so; a first-id verdict whose
    section is not a class section disclaims the row it would land on and is
    held. A co-id's verdict is the row's only when its section is a class
    section; with any other section it is the extra-sections lane's verdict
    on the row outside the class sections that shares the id (the §1 twins:
    on the first run their keeps landed here as conflicts), returned as a
    note -- and when no such row carries the id the note would be untrue, so
    that is held as a conflict. Two verdicts that ARE the row's and differ is
    a conflict too. Docstring at the top of the module: "Which row a verdict
    is about"."""
    own: list[tuple[str, dict]] = []
    notes: list[str] = []
    for x in r.ids:
        d = decisions.get(x)
        if d is None:
            continue
        sec = d.get("section")
        if _is_class_section(sec):
            own.append((x, d))
        elif x == r.id:
            return None, ("section_disclaims_row",
                          f"{r.id}: its own verdict carries section {sec!r}, which disclaims this row"), notes
        elif has_extra_row(x):
            notes.append(f"{r.id}: {x} {d['verdict']} carries section {sec!r} -- the extra-sections lane's verdict "
                         f"on the row outside the class sections that shares the id, not this row's")
        else:
            return None, ("conflicting_verdicts",
                          f"{r.id}: {x} {d['verdict']} carries section {sec!r} but no row outside the class "
                          f"sections carries {x}"), notes
    if not own:
        return None, None, notes
    verdicts = {d["verdict"] for _x, d in own}
    if len(verdicts) > 1:
        return None, ("conflicting_verdicts", f"{r.id}: co-ids carry differing verdicts {sorted(verdicts)}"), notes
    return own[0][1], None, notes


def assemble(text: str, probes: dict, final: list[dict], lane_rows: dict[str, dict], *,
             date: str, drop_previously_struck: bool = False) -> Result:
    """Pure: the same inputs give the same outputs. Never touches disk."""
    lines = text.split("\n")
    rows = scan_member_rows(lines)
    by_id: dict[str, Row] = {}
    duplicate_rows: list[str] = []
    for r in rows:
        for x in r.ids:
            if x in by_id:
                duplicate_rows.append(x)
            by_id.setdefault(x, r)
    tags = _GEN.declared_class_tags(text)
    index_of = scan_index_rows(lines)
    class_row_of = scan_class_rows(lines)
    decisions = {d["id"]: d for d in final}
    class_ids = set(by_id)
    # The census keys: the first id of every LIVE member row. A struck row's
    # first id is the extra lane's when a §1 row still carries it (DEF-538).
    primary_ids = {r.id for r in rows if not r.struck}
    class_lines = {j for _n, s, e in section_ranges(lines) for j in range(s, e)}
    exclude = class_lines | set(index_of.values()) | set(class_row_of.values())
    stop = next((i for i, ln in enumerate(lines) if ln.startswith("## Appendix")), len(lines))

    def has_extra_row(x: str) -> bool:
        return find_extra_row(lines, x, exclude, stop) is not None

    delete: set[int] = set()
    replace: dict[int, str] = {}
    retired: set[str] = set()
    struck_md: list[str] = []
    folded_md: list[str] = []
    prior_md: list[str] = []
    a4_rows: list[str] = []
    report: dict = {
        "date": date, "live_before": sum(1 for r in rows if not r.struck),
        "keeps_written": 0, "index_anchors_synced": 0, "struck": [], "folded": [],
        "previously_struck_dropped": 0, "extra_struck": [],
        "verdicts_for_unknown_ids": [], "duplicate_member_rows": duplicate_rows,
        "co_id_rows": sorted(r.id for r in rows if len(r.ids) > 1 and not r.struck),
        "co_id_extra_verdicts": [], "extra_rows_citing_retired_ids": [],
        "class_tag_changes": [], "mixed_axes": [], "widened_rows": [], "probes_retired": [],
        **{k: [] for k in _HELD_KEYS},
    }

    def tombstone(r_ids: list[str]) -> None:
        for x in r_ids:
            j = index_of.get(x)
            if j is not None:
                replace[j] = _tombstone_index(lines[j], x)

    # 1. Every §2 member row gets exactly one outcome.
    pending: dict[str, list[tuple[Row, dict, str, dict]]] = {}
    untouched: dict[str, list[tuple[Row, dict | None]]] = {}

    def hold(r: Row, key: str, note: str, d: dict | None) -> None:
        report[key].append(note)
        untouched.setdefault(r.section, []).append((r, d))

    for r in rows:
        if r.struck:
            if drop_previously_struck:
                delete.add(r.idx)
                prior_md.append(_struck_entry("previously struck (kept as PRIOR TEXT until this rebuild)", r, None, None))
                retired.update(r.ids)
                tombstone(r.ids)
                report["previously_struck_dropped"] += 1
            continue
        d, held, notes = _decision_for(r, decisions, has_extra_row)
        report["co_id_extra_verdicts"].extend(notes)
        if held:
            hold(r, held[0], held[1], None)
            continue
        if d is None:
            hold(r, "no_verdict", r.id, None)
            continue
        v = d["verdict"]
        if v == "unresolved":
            hold(r, "unresolved", r.id, d)
        elif v == "keep":
            lane = _lane_entry(lane_rows, [d["id"], r.id, *r.ids], "anchor") or {}
            if not (lane.get("anchor") and lane.get("body")):
                hold(r, "keep_without_text", r.id, d)
                continue
            sev_in = _severity_of(r.cells)
            if sev_in is None:
                hold(r, "severity_unreadable", f"{r.id}: severity cell {r.cells[3] if len(r.cells) > 3 else ''!r}", d)
                continue
            sev_out = d.get("severity") or sev_in
            if _RANK[sev_out] > _RANK[sev_in]:
                hold(r, "severity_refused", f"{r.id}: {sev_out} is below the row's {sev_in}", d)
                continue
            pending.setdefault(r.section, []).append((r, lane, sev_out, d))
        elif v == "strike":
            delete.add(r.idx)
            struck_md.append(_struck_entry("struck", r, d, _lane_entry(lane_rows, [d["id"], r.id, *r.ids], "strike_evidence")))
            retired.update(r.ids)
            tombstone(r.ids)
            report["struck"].append(r.id)
        elif v == "fold":
            owner = d.get("fold_into")
            owner_row = by_id.get(owner) if isinstance(owner, str) else None
            owner_d, _h, _n = _decision_for(owner_row, decisions, has_extra_row) if owner_row else (None, None, [])
            owner_live = (owner_row is not None and not owner_row.struck and owner_row is not r
                          and (owner_d is None or owner_d["verdict"] in ("keep", "unresolved")))
            if not owner_live:
                hold(r, "fold_refused", f"{r.id}: fold_into {owner!r} is not a live row that stays", d)
                continue
            delete.add(r.idx)
            folded_md.append(_struck_entry("folded", r, d, _lane_entry(lane_rows, [d["id"], r.id, *r.ids], "strike_evidence")))
            retired.update(r.ids)
            tombstone(r.ids)
            a4_rows.append(f"| {r.id_cell} ({r.section}) -- folded {date} in the third rebuild "
                           f"| its substance is carried by the owning row | **`{owner}`** |")
            report["folded"].append(f"{r.id} -> {owner}")

    for d in final:
        if d["id"] not in class_ids and _is_class_section(d.get("section")):
            report["verdicts_for_unknown_ids"].append(d["id"])

    # 2. Class tags, per axis: agreement moves the index cell; disagreement makes
    #    the axis MIXED; a placeholder refuses the class's keeps.
    axes = (("population", 4, _GEN.POPULATIONS), ("audience", 5, _GEN.AUDIENCES))
    for name, _s, _e in section_ranges(lines):
        keeps = pending.get(name, [])
        stay = untouched.get(name, [])
        if not keeps and not stay:
            continue
        ctags = tags.get(name, (None, None))
        if any(ctags[i] not in vocab and ctags[i] != _GEN.MIXED for i, (_l, _c, vocab) in enumerate(axes)):
            for r, _lane, _sev, _d in keeps:
                report["row_refused"].append(f"{r.id}: class {name} declares no usable tag {ctags!r}; not rewritten")
                untouched.setdefault(name, []).append((r, _d))
            continue

        def label(r: Row, d: dict | None, axis: int, ctag: str, vocab: tuple[str, ...]) -> str | None:
            """The row's effective token on one axis: its final label, else its
            own cell, else the class token (never on a MIXED axis)."""
            key = "population" if axis == 4 else "audience"
            fin = d.get(key) if d else None
            if fin in vocab:
                return fin
            own = _own_tags(r.cells)[axis - 4]
            if own is not None:
                return own
            return ctag if ctag in vocab else None

        eff: dict[int, tuple[str | None, str | None]] = {}
        refused_here: set[int] = set()
        for r, _lane, _sev, d in keeps:
            pair = tuple(label(r, d, ax, ctags[i], vocab) for i, (_l, ax, vocab) in enumerate(axes))
            if None in pair:
                report["row_refused"].append(f"{r.id}: no {'population' if pair[0] is None else 'audience'} label on a MIXED axis")
                refused_here.add(r.idx)
                untouched.setdefault(name, []).append((r, d))
                continue
            eff[r.idx] = pair  # type: ignore[assignment]
        for r, d in stay:
            eff[r.idx] = tuple(label(r, d, ax, ctags[i], vocab) for i, (_l, ax, vocab) in enumerate(axes))  # type: ignore[assignment]
        keeps = [k for k in keeps if k[0].idx not in refused_here]
        stay = untouched.get(name, [])

        new_tags: list[str | None] = list(ctags)
        index_cells: list[str | None] = [None, None]
        for i, (axis_name, _ax, vocab) in enumerate(axes):
            ctag = ctags[i]
            tokens = {eff[r.idx][i] for r, *_ in keeps} | {eff[r.idx][i] for r, _d in stay}
            tokens.discard(None)
            if ctag == _GEN.MIXED:
                continue
            if not tokens or tokens == {ctag}:
                continue
            if len(tokens) == 1:
                new = next(iter(tokens))
                new_tags[i] = new
                index_cells[i] = f"{new} (re-derived {date}; was {ctag})"
                report["class_tag_changes"].append({"section": name, "axis": axis_name, "was": ctag, "now": new})
            else:
                new_tags[i] = _GEN.MIXED
                index_cells[i] = _GEN.MIXED
                report["mixed_axes"].append({"section": name, "axis": axis_name, "was": ctag, "tokens": sorted(tokens)})
        if any(c is not None for c in index_cells) and name in class_row_of:
            j = class_row_of[name]
            replace[j] = _class_cells_rewritten(lines[j], index_cells[0], index_cells[1])
        rows_need_cells = _GEN.MIXED in new_tags
        for r, lane, sev, _d in keeps:
            pair = eff[r.idx]
            try:
                replace[r.idx] = build_row(r.id_cell, lane["anchor"], lane["body"], sev,
                                           (pair[0], pair[1]) if rows_need_cells else None)  # type: ignore[arg-type]
                report["keeps_written"] += 1
                for x in r.ids:
                    if x in index_of:
                        replace[index_of[x]] = _index_with_anchor(lines[index_of[x]], lane["anchor"])
                        report["index_anchors_synced"] += 1
            except Refused as exc:
                report["row_refused"].append(str(exc))
                untouched.setdefault(name, []).append((r, _d))
        if rows_need_cells:
            for r, _d in stay:
                if len(r.cells) >= 6 or r.idx in replace:
                    continue
                pair = eff[r.idx]
                if None in pair:
                    report["row_refused"].append(f"{r.id}: cannot widen to a MIXED row without both tags")
                    continue
                widened = r.line.rstrip() + f" {pair[0]} | {pair[1]} |"
                if len(_GEN.member_cells(widened)) == 6:
                    replace[r.idx] = widened
                    report["widened_rows"].append(f"{r.id}: {pair[0]} | {pair[1]}")
                else:
                    report["row_refused"].append(f"{r.id}: could not widen to a MIXED row")

    # 3. Extra sections (§1 / §3 / §4 / §5): strike-or-keep only, never a rewrite.
    #    In this pass a verdict is an extra row's when its id is not a live
    #    census key and its section is not a class section -- so the extra
    #    lane's strike on a co-id reaches the §1 twin that shares a §2 row's id
    #    pair instead of vanishing because the id is also a member id. A row
    #    that carries two ids is struck both or neither: every other id needs a
    #    strike of its own, or a member row that leaves in this run. (The
    #    member-row pass above retires every id on a struck member row; that
    #    is the strike verb's rule and is not repeated here.)
    for d in final:
        if d["id"] in primary_ids or _is_class_section(d.get("section")):
            continue
        if d["verdict"] != "strike":
            if d["verdict"] not in ("keep", "unresolved"):  # the lane's two legal encodings
                report["extra_unresolved"].append(
                    f"{d['id']}: {d['verdict']} is not a verdict the extra-sections lane returns "
                    f"(keep or strike only); the row stays")
            continue
        hit = find_extra_row(lines, d["id"], exclude, stop)
        if hit is None:
            report["extra_unresolved"].append(f"{d['id']}: no unique row outside the class sections")
            continue
        j, cell_ids = hit
        blocking = [x for x in cell_ids if x != d["id"]
                    and decisions.get(x, {}).get("verdict") != "strike"
                    and not (x in by_id and by_id[x].idx in delete)]
        if blocking:
            report["extra_unresolved"].append(
                f"{d['id']}: its row also carries {blocking} without a strike verdict; the row stays")
            continue
        if j in delete:
            continue
        delete.add(j)
        pseudo = Row(d["id"], cell_ids, " ".join(f"`{x}`" for x in cell_ids), d.get("section") or "extra",
                     j, lines[j], False, [])
        struck_md.append(_struck_entry("struck (outside the class sections)", pseudo, d, lane_rows.get(d["id"])))
        retired.update(cell_ids)
        tombstone(cell_ids)
        report["extra_struck"].extend(cell_ids)

    # 3b. A row outside the class sections that stays while an id it carries was
    #     retired above: the strike verb's own precedent (DEF-538+LG-5, 2026-08-20)
    #     and the structural cut's decision -- named and counted, never held.
    citing: dict[int, list[str]] = {}
    for x in sorted(retired):
        hit = find_extra_row(lines, x, exclude, stop)
        if hit is not None and hit[0] not in delete:
            citing.setdefault(hit[0], []).append(x)
    for j, ids in sorted(citing.items()):
        report["extra_rows_citing_retired_ids"].append(f"line {j + 1}: still carries retired {ids}")

    # 4. Apply: replacements first, then the A4 rows, then deletions from the bottom.
    out_lines = list(lines)
    for j, new in replace.items():
        if j not in delete:
            out_lines[j] = new
    if a4_rows:
        a4 = _heading_index(out_lines, "## Appendix A4")
        last = None
        if a4 is not None:
            for j in range(a4 + 1, len(out_lines)):
                if out_lines[j].startswith("## "):
                    break
                if out_lines[j].startswith("|"):
                    last = j
        if last is None:
            report["fold_refused"].append("Appendix A4 has no table to append to; the fold rows were not written")
        else:
            out_lines[last + 1:last + 1] = a4_rows
            delete = {j + len(a4_rows) if j > last else j for j in delete}
    for j in sorted(delete, reverse=True):
        del out_lines[j]
    new_text = "\n".join(out_lines)

    # 5. Probes: a struck or folded row loses its probe; _count re-derived.
    probes_out = dict(probes)
    before = probes.get("probes", [])
    kept = [p for p in before if p.get("id") not in retired]
    probes_out["probes"] = kept
    probes_out["_count"] = len(kept)
    probes_out["_generated"] = f"{date} rebuild (third)"
    report["probes_retired"] = sorted({p.get("id") for p in before} & retired)

    d_after = _GEN.derive(new_text)
    report["live_after"] = d_after["live_total"]
    report["population_live_after"] = d_after["population_live"]
    report["audience_live_after"] = d_after["audience_live"]
    report["tag_problems_after"] = d_after["tag_problems"]
    report["held"] = sorted({s.split(":")[0] for k in _HELD_KEYS for s in report[k]})

    md = [
        f"# Struck in the {date} rebuild -- record-branch payload",
        "",
        "_Generated by `scripts/ledger_rebuild_assemble.py`. RECORD SURFACE -- do not edit, re-anchor or re-count._",
        "",
        f"## Struck ({len(struck_md)})", "", *struck_md,
        f"## Folded ({len(folded_md)})", "", *folded_md,
        f"## Previously struck, retained as PRIOR TEXT until this rebuild ({len(prior_md)})", "", *prior_md,
    ]
    return Result(text=new_text, probes=probes_out, struck_md="\n".join(md) + "\n", report=report)


def regenerate_regions(text: str, probe_ids: set[str], *, passes: int = 3) -> tuple[str, list[dict]]:
    """Run the generator's own repair over the rebuilt text with its probe
    reader answering the REBUILT roster, so the probe-roster region judges the
    file that ships, not the live tree's. Returns the text and every residual
    drift entry (the non-writable regions are reported, never hidden). The
    reader is restored afterwards: the generator module is shared in-process."""
    saved = _GEN._probe_ids
    _GEN._probe_ids = lambda: set(probe_ids)
    try:
        for _ in range(passes):
            drift = _GEN.find_drift(text)
            text, applied = _GEN.apply_writable(text, drift)
            if not applied:
                break
        residual = [{"region": d["region"], "detail": d.get("detail", "")} for d in _GEN.find_drift(text)]
    finally:
        _GEN._probe_ids = saved
    return text, residual


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # strict decode: a structured answer
        raise ValueError(f"{path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", required=True, type=Path, help="the STAGED FORWARD_LEDGER.md (a scratch clone's)")
    ap.add_argument("--probes", required=True, type=Path, help="the staged LEDGER_PROBES.json")
    ap.add_argument("--lanes", required=True, type=Path, help="directory of the workflow's lane JSONs")
    ap.add_argument("--final", required=True, type=Path, help="verdicts.final.json (the workflow's merged list)")
    ap.add_argument("--out", required=True, type=Path, help="output directory (created; refused if it already holds a rebuild)")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD; the only timestamp the outputs carry")
    ap.add_argument("--drop-previously-struck", action="store_true",
                    help="move the rows already struck (~~) to struck-rows.md instead of retaining them (1-D's call)")
    ap.add_argument("--max-held", type=int, default=0,
                    help="the most rows that may be left untouched for the operator before the run is refused (default 0)")
    ap.add_argument("--force", action="store_true", help="overwrite an --out that already holds a rebuild")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)

    if not _DATE.match(args.date):
        print(f"--date must be YYYY-MM-DD, got {args.date!r}", file=sys.stderr)
        return 2
    try:
        text = args.ledger.read_text(encoding="utf-8")
        probes = load_probes(_read_json(args.probes), args.probes.name)
        final = load_final(_read_json(args.final))
        if not args.lanes.is_dir():
            raise ValueError(f"{args.lanes}: not a directory")
        lane_rows, duplicates = load_lane_rows(args.lanes)
    except (OSError, ValueError) as exc:  # strict decode: a structured answer
        print(f"ledger_rebuild_assemble: {exc}", file=sys.stderr)
        return 2
    if not _GEN.ledger_sections(text):
        print("ledger_rebuild_assemble: the ledger parses to no class sections -- refusing an empty rebuild",
              file=sys.stderr)
        return 1
    existing = [n for n in OUTPUT_NAMES if (args.out / n).exists()]
    if existing and not args.force:
        print(f"ledger_rebuild_assemble: {args.out} already holds a rebuild ({', '.join(existing)}); "
              "a second run would replace the record payload -- use a fresh --out, or --force", file=sys.stderr)
        return 3

    result = assemble(text, probes, final, lane_rows, date=args.date,
                      drop_previously_struck=args.drop_previously_struck)
    rep = result.report
    rep["duplicate_lane_rows"] = duplicates
    if len(rep["held"]) > args.max_held:
        print(f"ledger_rebuild_assemble: {len(rep['held'])} row(s) would be left untouched, above --max-held "
              f"{args.max_held}; nothing written. Held: {' '.join(rep['held'])}", file=sys.stderr)
        for k in _HELD_KEYS:
            for note in rep[k]:
                print(f"  {k}: {note}", file=sys.stderr)
        return 3

    rebuilt_text, residual = regenerate_regions(result.text, {p.get("id") for p in result.probes["probes"]})
    rep["residual_drift"] = residual
    args.out.mkdir(parents=True, exist_ok=True)
    _GEN._atomic_write(args.out / OUTPUT_NAMES[1], json.dumps(result.probes, indent=1, ensure_ascii=False) + "\n")
    _GEN._atomic_write(args.out / OUTPUT_NAMES[0], rebuilt_text)
    _GEN._atomic_write(args.out / OUTPUT_NAMES[2], result.struck_md)
    _GEN._atomic_write(args.out / OUTPUT_NAMES[3], json.dumps(rep, indent=1, ensure_ascii=False) + "\n")

    if args.json:
        print(json.dumps(rep, indent=1, ensure_ascii=False))
    else:
        print(f"assembled {args.out / OUTPUT_NAMES[0]}: live {rep['live_before']} -> {rep['live_after']}; "
              f"{rep['keeps_written']} rewritten, {len(rep['struck'])} struck, {len(rep['folded'])} folded, "
              f"{rep['previously_struck_dropped']} previously-struck moved to the record, "
              f"{len(rep['extra_struck'])} struck outside the class sections; {len(rep['held'])} row(s) held "
              f"(see assemble-report.json); {len(rep['probes_retired'])} probe(s) retired; "
              f"{len(rep['co_id_extra_verdicts'])} co-id verdict(s) left to their extra row, "
              f"{len(rep['extra_rows_citing_retired_ids'])} extra row(s) still citing a retired id; "
              f"{len(residual)} residual drift entr{'y' if len(residual) == 1 else 'ies'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
