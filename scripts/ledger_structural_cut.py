#!/usr/bin/env python3
"""Cut the rebuilt forward ledger down to forward work, and record what left.

Why this exists
---------------
The third rebuild (the 2026-09-20 adjudication and its reconciliation pass)
resolved every live row of ``task-packs/FORWARD_LEDGER.md`` but left the
file's history in place: every
row struck since the previous rebuild, the session notes above the contract,
the DEC-25 essay, the all-closed classes, ``§7`` and Appendix C. Under DEC-31
the ledger ships, and a public ledger that carries its war stories is a
public repo whose forward tracker is two-thirds history a stranger reads as
the present. The row that owns the rebuild says the cut must be re-runnable
at seed time, and the assembler could not do it: it is verdict-driven and a
second run over the 1-C'd file would refuse on the rows 1-C filed. So the cut
is its own pass, driven by the file's own markers and by named headings, and
it never writes a live path -- 1-D's plan copies its output over the
rebuilt file and the live write is a later act.

What it does, in order
----------------------
0. ``--strike-id ID`` (repeatable): strikes that id in the id cell of the one
   table row outside the class sections that carries it unstruck -- a co-id
   left live beside a struck one when its pack landed -- so the row leaves
   with the rest and the run reproduces from the same input with the same
   flags. Refused when no row or several rows carry it.
1. Drops every STRUCK ROW: a class-section member row the generator reads as
   struck (``_is_struck``: first cell opens ``~~``); an Appendix B index row
   struck by the generator's rule, or one there whose id cell is wholly
   struck although its section cell is not a ``§C`` one (the ``§4A``-homed
   rows the completeness module's ``DEF-593`` records); a row of any other
   table (§1's numbered launch gates, §3-§6's id-list rows) whose id cell has
   every id-shaped token inside a ``~~`` span -- so ``| 1 | ~~`DEF-426`~~
   `PR-2` |`` stays (a live co-id) and ``| 8 | ~~`DEF-425`~~ ~~`DEF-455`~~
   |`` goes. **The Appendix A crosswalks (A, A2-A5) are never touched**: their
   job is that a citation does not dead-end, and a struck id there is a
   record, not a closed row; any such row is reported, not dropped. A struck
   row whose id still carries a probe is a refusal (the generator's own
   probe-roster region), never a silent drop.
2. Drops every h2 block whose title starts with a ``--drop-h2`` prefix
   (repeatable; each prefix must match at least one h2), every paragraph
   that starts with a ``--drop-paragraph`` text (exactly one match each; a
   paragraph that runs into a table row is refused, because a paragraph is
   bounded by blank lines and a table is not prose), and every
   ``--drop-class-section §CN`` with its class-index row (refused when the
   section still has a live row).
3. Moves every ``--move-h2-into-contract TITLE`` block to the end of the
   ``## The contract`` section, its headings demoted one level (a ``#`` line
   inside a code fence is not a heading).
4. Refuses when any h2 still sits above the contract afterwards: the roster
   above the contract is the history blocks, and a block nobody named is a
   block nobody decided about.
5. Replaces the header note (the paragraph opening ``_The single forward-work
   tracker.``) with ``--rebuilt-note``'s file, so the doorway names this
   rebuild and the record file.
6. Regenerates the derived regions with the generator's own repair, the probe
   reader answering the roster it was given; any residual non-writable drift
   is a refusal, and every literal repair is recorded as a rewrite.

Then it proves the cut dropped nothing it was not told to. The proof that
carries weight is file-wide: the set of live id-shaped tokens across EVERY
table row (class sections, the launch gates, the queues, the appendices) after
the cut must equal the input's set minus the rows inside a dropped block or
class section -- two thirds of the ledger's live ids sit outside the class
sections, and ``derive()`` never sees them. Beside it: the live member ids,
the live total and the population and audience splits are unchanged; the
class sections that remain are exactly the input's minus the ones named; no
row it would classify as struck survives; and the input lines partition into
kept and removed (a bookkeeping check on the index arithmetic, not a proof).

What it writes (all under ``--out``, none of its inputs; an ``--out`` that
already holds a cut is refused, in ``--dry-run`` too)
------------------------------------------------------------------------
* ``FORWARD_LEDGER.cut.md`` -- the cut ledger, regions converged. This is the
  script's output, not the finished file: 1-D's hand pass and the row verbs
  run over it afterwards, so the finished pair is what the plan names, never
  this file.
* ``cut-<date>.md`` -- the record-branch payload: every dropped block, row and
  paragraph verbatim, grouped by where it was, plus each rewrite as old/new.
* ``cut-report.json`` -- every count, every id dropped, every heading whose
  typed count may now be stale (a section that lost rows), every surviving
  line that still points at a dropped paragraph or block
  (``pointers_to_review``), the rewrites and any residual drift.

The probes file is read (its ``_count`` must agree with its rows, as the row
verbs require) and never written: a struck row has no probe by the time this
runs, so the roster does not move.

Usage
-----
    python scripts/ledger_structural_cut.py --ledger <rebuilt>.md --probes <rebuilt>.json \\
        --out <dir> --date 2026-09-20 --strike-id PR-2 \\
        --drop-h2 "▶ START HERE" --drop-h2 "⚠ Session note" --drop-h2 "§7 —" --drop-h2 "Appendix C —" \\
        --move-h2-into-contract "How this file defends itself" \\
        --drop-paragraph "⚠ **From the 2026-08-20 rebuild until 2026-09-02" \\
        --drop-paragraph "⚠ **\\`DEC-25\\`, 2026-08-20" --drop-paragraph "⚠ **Two consequences are live NOW" \\
        --drop-class-section §C47 --rebuilt-note <note>.md [--dry-run] [--json]

Exit 0 when the outputs were written (or ``--dry-run`` printed the report);
2 when the cut was refused or an input was unreadable, with the reason on
stderr and nothing written; 3 when ``--out`` already holds a cut.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load(name: str):
    """A sibling script as a module (``scripts/`` is not a package); an
    already-imported copy is reused, as the assembler and the row tool do."""
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, "__file__", None):
        return existing
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_GEN = _load("generate_ledger_regions")  # the grammar's one home
_ASM = _load("ledger_rebuild_assemble")  # section ranges, probes loader, region regen

OUTPUT_LEDGER = "FORWARD_LEDGER.cut.md"
OUTPUT_REPORT = "cut-report.json"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: An id as the ledger writes one: ``DEF-410l``, ``LG-14``, ``PR-3``, ``DEC-31``.
_ID_SHAPE = _GEN._ID_SHAPE  # one shape, the grammar's (its cell_ids filters through it too)
_BACKTICKED = re.compile(r"`([^`]+)`")
_STRUCK_SPAN = re.compile(r"~~[^~]*~~")
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_HEADER_NOTE_START = "_The single forward-work tracker."
_CONTRACT_TITLE = "The contract"
_CROSSWALK_TITLE = "Appendix A"  # A, A2, A3, A4, A5: never cut, never struck away
_FENCES = ("```", "~~~")
#: The fence the payload wraps verbatim text in: tildes, so a backtick fence
#: inside a session note cannot close it; a line opening with it is refused.
_FENCE = "~~~~"
#: A surviving line that names a dropped block or paragraph by these words is
#: a pointer to review (``see the DEC-25 note above``, ``Struck rows are in §7``).
_POINTER_WORDS = re.compile(r"\b(above|below|see|note|in §|are in)\b", re.I)


class Refused(Exception):
    """A cut this script will not write; the caller prints why and exits 2."""


@dataclass
class Options:
    date: str
    drop_h2: list[str] = field(default_factory=list)
    move_h2_into_contract: list[str] = field(default_factory=list)
    drop_class_sections: list[str] = field(default_factory=list)
    drop_paragraphs: list[str] = field(default_factory=list)
    strike_ids: list[str] = field(default_factory=list)
    rebuilt_note: str | None = None


@dataclass
class Result:
    text: str
    payload: str
    report: dict


# --------------------------------------------------------------------------
# Reading the file
# --------------------------------------------------------------------------
def h2_ranges(lines: list[str]) -> list[tuple[str, int, int]]:
    """``[(title, start, end)]`` for every ``## `` heading; a block ends at
    the next h2 or at EOF."""
    starts = [(i, ln[3:].strip()) for i, ln in enumerate(lines) if ln.startswith("## ")]
    out: list[tuple[str, int, int]] = []
    for k, (idx, title) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        out.append((title, idx, end))
    return out


def paragraph_range(lines: list[str], start_text: str, flag: str = "--drop-paragraph") -> tuple[int, int]:
    """``(start, end)`` of the one blank-line-delimited paragraph whose first
    line opens with ``start_text``; zero or several matches are refused, and
    so is a paragraph that runs into a table row (a table is not prose, and a
    paragraph that reaches one would take live rows with it)."""
    hits = [i for i, ln in enumerate(lines) if ln.startswith(start_text)
            and (i == 0 or not lines[i - 1].strip())]
    if len(hits) != 1:
        raise Refused(f"{flag} {start_text!r} opens {len(hits)} paragraph(s), not one")
    s = hits[0]
    e = s
    while e < len(lines) and lines[e].strip():
        if lines[e].lstrip().startswith("|"):
            raise Refused(f"{flag} {start_text!r}: the paragraph runs into a table row at line {e + 1}; "
                          "a paragraph ends at a blank line and a table is not prose")
        e += 1
    return s, e


def _cells(line: str) -> list[str]:
    return [c.strip() for c in _UNESCAPED_PIPE.split(line.strip().strip("|"))]


def id_cell(cells: list[str]) -> str | None:
    """The cell that carries a table row's ids: the first, or the second when
    the first is an ordinal (``| 1 |``, ``| 5 ○ |`` -- §1's numbered shape).
    ``None`` when neither carries an id-shaped token (a header, a class-index
    row, a population table)."""
    for cell in cells[:2]:
        if any(_ID_SHAPE.match(tok) for tok in _BACKTICKED.findall(cell)):
            return cell
        if "`" in cell:
            return None
    return None


def cell_wholly_struck(cell: str) -> bool:
    """True when every id-shaped token in ``cell`` sits inside a ``~~`` span.
    ``~~`DEF-426`~~ `PR-2``` is not struck (a live co-id); ``~~`DEC-12`
    `DEF-412b`~~`` and ``~~`DEF-425`~~ ~~`DEF-455`~~`` are."""
    ids = [tok for tok in _BACKTICKED.findall(cell) if _ID_SHAPE.match(tok)]
    if not ids:
        return False
    rest = _STRUCK_SPAN.sub("", cell)
    return not any(_ID_SHAPE.match(tok) for tok in _BACKTICKED.findall(rest))


def row_ids(line: str) -> list[str]:
    """Every id-shaped token in the row's id cell, struck or not."""
    cell = id_cell(_cells(line))
    if cell is None:
        return []
    return [tok for tok in _BACKTICKED.findall(cell) if _ID_SHAPE.match(tok)]


def live_row_ids(line: str) -> list[str]:
    """The id-shaped tokens in the row's id cell that sit OUTSIDE a ``~~`` span."""
    cell = id_cell(_cells(line))
    if cell is None:
        return []
    return [tok for tok in _BACKTICKED.findall(_STRUCK_SPAN.sub("", cell)) if _ID_SHAPE.match(tok)]


def _crosswalk_lines(lines: list[str]) -> set[int]:
    """Every line index under an ``## Appendix A…`` heading."""
    out: set[int] = set()
    for title, s, e in h2_ranges(lines):
        if title.startswith(_CROSSWALK_TITLE):
            out.update(range(s, e))
    return out


def _appendix_b_range(lines: list[str]) -> tuple[int, int] | None:
    b_start = _ASM._heading_index(lines, "## Appendix B")
    if b_start is None:
        return None
    b_end = next((j for j in range(b_start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    return b_start, b_end


def classify_struck_rows(lines: list[str]) -> dict[int, str]:
    """``{line index: where}`` for every row the cut drops as struck:
    ``class`` (a member row inside a ``§CN`` section, the generator's rule),
    ``appendix-b`` (an index row struck by the generator's rule, or a row
    there whose id cell is wholly struck but whose section cell is not a
    ``§C`` one) or ``table`` (any other table row whose id cell is wholly
    struck). The Appendix A crosswalks are never classified."""
    out: dict[int, str] = {}
    in_class: set[int] = set()
    for _name, start, end in _ASM.section_ranges(lines):
        for j in range(start, end):
            in_class.add(j)
            if _GEN._MEMBER_ROW.match(lines[j]) and _GEN._is_struck(lines[j]):
                out[j] = "class"
    b = _appendix_b_range(lines)
    b_lines: set[int] = set()
    if b is not None:
        b_start, b_end = b
        b_lines = set(range(b_start, b_end))
        for j in range(b_start, b_end):
            ln = lines[j]
            m = _GEN._APPENDIX_B_ROW.match(ln)
            if m and m.group(1):
                out[j] = "appendix-b"
            elif not m and ln.startswith("|"):
                cell = id_cell(_cells(ln))
                if cell is not None and cell_wholly_struck(cell):
                    out[j] = "appendix-b"
    crosswalk = _crosswalk_lines(lines)
    for j, ln in enumerate(lines):
        if j in out or j in in_class or j in b_lines or j in crosswalk:
            continue
        if not ln.startswith("|"):
            continue
        cell = id_cell(_cells(ln))
        if cell is not None and cell_wholly_struck(cell):
            out[j] = "table"
    return out


def struck_rows_kept_in_crosswalks(lines: list[str]) -> list[int]:
    """Crosswalk rows whose id cell is wholly struck -- reported, never dropped."""
    return sorted(j for j in _crosswalk_lines(lines)
                  if lines[j].startswith("|")
                  and (c := id_cell(_cells(lines[j]))) is not None and cell_wholly_struck(c))


def live_table_ids(lines: list[str], skip: set[int] | None = None) -> set[str]:
    """The live id-shaped tokens across EVERY table row of the file (class
    sections, launch gates, queues, appendices), skipping the line indices in
    ``skip`` -- the file-wide population the cut must conserve."""
    skip = skip or set()
    out: set[str] = set()
    for j, ln in enumerate(lines):
        if j in skip or not ln.startswith("|"):
            continue
        out.update(live_row_ids(ln))
    return out


def _demote(line: str) -> str:
    return "#" + line if line.startswith("#") else line


def _heading_of(lines: list[str], idx: int) -> str:
    """The nearest heading (h2 or h3) at or above ``idx``, for the report."""
    for j in range(idx, -1, -1):
        if lines[j].startswith("## ") or lines[j].startswith("### "):
            return lines[j].lstrip("# ").strip()
    return "(top of file)"


def _pointer_tokens(opts: Options) -> list[str]:
    """What a surviving line could still point at: the lead id of each dropped
    paragraph and the section token (``§7``, ``Appendix C``) of each dropped h2."""
    toks: list[str] = []
    for start in opts.drop_paragraphs:
        toks += [t for t in _BACKTICKED.findall(start) if _ID_SHAPE.match(t)]
    for prefix in opts.drop_h2:
        m = re.match(r"^(§\d+|Appendix [A-Z]\d*)\b", prefix)
        if m:
            toks.append(m.group(1))
    return toks


# --------------------------------------------------------------------------
# The cut
# --------------------------------------------------------------------------
def cut(text: str, probe_ids: set[str], opts: Options) -> Result:
    lines = text.split("\n")
    rewrites: list[dict[str, object]] = []
    report: dict[str, object] = {
        "date": opts.date, "lines_in": len(lines), "strike_ids": [],
        "blocks_dropped": [], "blocks_moved": [], "paragraphs_dropped": [],
        "class_sections_dropped": [], "rows_dropped": {"class": [], "table": [], "appendix-b": []},
        "struck_rows_kept_in_crosswalks": [], "headings_that_lost_rows": [],
        "pointers_to_review": [], "live_table_ids": {}, "rewrites": rewrites, "residual_drift": [],
    }

    # 0. --strike-id: the input edit that makes a run reproducible from its
    #    flags. Its population is the launch-gate and queue tables: never a
    #    class section (the verbs' business), never the index or a crosswalk.
    out_of_reach: set[int] = set(_crosswalk_lines(lines))
    for _n, s, e in _ASM.section_ranges(lines):
        out_of_reach.update(range(s, e))
    if (b := _appendix_b_range(lines)) is not None:
        out_of_reach.update(range(*b))
    for rid in opts.strike_ids:
        hits = [j for j, ln in enumerate(lines)
                if j not in out_of_reach and ln.startswith("|") and rid in live_row_ids(ln)]
        if len(hits) != 1:
            raise Refused(f"--strike-id {rid}: {len(hits)} table row(s) outside the class sections, "
                          "the index and the crosswalks carry it unstruck, not one")
        j = hits[0]
        new = lines[j].replace(f"`{rid}`", f"~~`{rid}`~~", 1)
        rewrites.append({"line_in": j + 1, "old": lines[j], "new": new, "why": f"--strike-id {rid} on the input"})
        lines[j] = new
        report["strike_ids"].append(rid)
    text = "\n".join(lines)

    removed: dict[int, str] = {}   # line index -> group

    def take(idx: int, group: str) -> None:
        if idx in removed:
            raise Refused(f"line {idx + 1} would leave the file twice ({removed[idx]} and {group})")
        removed[idx] = group

    blocks = h2_ranges(lines)
    contract = [b for b in blocks if b[0].startswith(_CONTRACT_TITLE)]
    if len(contract) != 1:
        raise Refused(f"expected exactly one `## {_CONTRACT_TITLE}` heading, found {len(contract)}")
    _ctitle, c_start, c_end = contract[0]

    # 1. Struck rows.
    struck = classify_struck_rows(lines)
    for j, where in sorted(struck.items()):
        ids = row_ids(lines[j]) if where != "class" else \
            [m.group(2) for m in [_GEN._MEMBER_ID.match(lines[j])] if m]
        probed = sorted(set(ids) & probe_ids)
        if probed:
            raise Refused(f"struck row at line {j + 1} still carries a probe for {probed}; retire it first")
        take(j, f"row:{where}")
        for i in ids or [lines[j][:40]]:
            if i not in report["rows_dropped"][where]:
                report["rows_dropped"][where].append(i)
    report["struck_rows_kept_in_crosswalks"] = [
        {"line_in": j + 1, "text": lines[j][:160]} for j in struck_rows_kept_in_crosswalks(lines)]

    # 2. Blocks, paragraphs, class sections.
    for prefix in opts.drop_h2:
        hits = [b for b in blocks if b[0].startswith(prefix)]
        if not hits:
            raise Refused(f"--drop-h2 {prefix!r} matches no h2 heading")
        for title, s, e in hits:
            if title.startswith(_CROSSWALK_TITLE):
                raise Refused(f"--drop-h2 {prefix!r} would drop the crosswalk {title!r}; the appendices are never cut")
            for j in range(s, e):
                if j not in removed:
                    take(j, f"block:{title}")
            report["blocks_dropped"].append(title)
    for start_text in opts.drop_paragraphs:
        s, e = paragraph_range(lines, start_text)
        for j in range(s, e):
            take(j, f"paragraph:{start_text}")
        report["paragraphs_dropped"].append(start_text)
    for name in opts.drop_class_sections:
        ranges = [r for r in _ASM.section_ranges(lines) if r[0] == name]
        if len(ranges) != 1:
            raise Refused(f"--drop-class-section {name}: found {len(ranges)} section(s)")
        _n, s, e = ranges[0]
        live = [lines[j] for j in range(s, e)
                if _GEN._MEMBER_ROW.match(lines[j]) and not _GEN._is_struck(lines[j])]
        if live:
            raise Refused(f"--drop-class-section {name}: it still has {len(live)} live row(s)")
        for j in range(s, e):
            if j not in removed:
                take(j, f"section:{name}")
        index_rows = [j for j, ln in enumerate(lines)
                      if (m := _GEN._CLASS_TABLE_ROW.match(ln)) and m.group(1) == name]
        if len(index_rows) != 1:
            raise Refused(f"--drop-class-section {name}: found {len(index_rows)} class-index row(s)")
        take(index_rows[0], f"section:{name}")
        report["class_sections_dropped"].append(name)

    # 3. Moved blocks: taken out here, re-inserted (demoted) after the contract.
    moved: list[tuple[str, list[int]]] = []
    for title in opts.move_h2_into_contract:
        hits = [b for b in blocks if b[0] == title]
        if len(hits) != 1:
            raise Refused(f"--move-h2-into-contract {title!r} matches {len(hits)} h2 heading(s), not one")
        _t, s, e = hits[0]
        if s >= c_start:
            raise Refused(f"--move-h2-into-contract {title!r}: the block is not above the contract")
        moved.append((title, [j for j in range(s, e) if j not in removed]))
        report["blocks_moved"].append(title)

    # 4. Nothing else may sit above the contract.
    moved_idx = {j for _t, js in moved for j in js}
    for title, s, e in blocks:
        if s < c_start and not all(j in removed or j in moved_idx for j in range(s, e)):
            raise Refused(f"the h2 block {title!r} sits above the contract and was neither dropped nor moved")

    # 5. Assemble: kept lines in order, the moved blocks at the end of the contract.
    kept_idx = [j for j in range(len(lines)) if j not in removed and j not in moved_idx]
    tail = [j for j in kept_idx if j >= c_end]
    head = [j for j in kept_idx if j < c_end]
    while head and not lines[head[-1]].strip():  # the contract's trailing blanks follow the moved blocks
        tail.insert(0, head.pop())
    order: list[tuple[int, str]] = [(j, lines[j]) for j in head]
    for title, js in moved:
        order.append((-1, ""))
        for j in js:
            order.append((j, lines[j]))
    order.extend((j, lines[j]) for j in tail)

    kept_before_rewrites = [ln for _j, ln in order if _j != -1]
    # Bookkeeping: every input line is kept once or removed once (the index
    # arithmetic above; a double take raises earlier). The proof is step 7.
    if Counter(lines) != Counter(kept_before_rewrites) + Counter(lines[j] for j in removed):
        raise Refused("the cut lost or duplicated a line; nothing written")

    out_lines: list[str] = []
    in_fence = False  # a `# comment` inside a moved block's code fence is not a heading
    for j, ln in order:
        if j in moved_idx and ln.startswith(_FENCES):
            in_fence = not in_fence
        if j in moved_idx and ln.startswith("#") and not in_fence:
            new = _demote(ln)
            rewrites.append({"line_in": j + 1, "old": ln, "new": new, "why": "moved under the contract"})
            out_lines.append(new)
        else:
            out_lines.append(ln)

    # 6. The header note.
    if opts.rebuilt_note is not None:
        s, e = paragraph_range(out_lines, _HEADER_NOTE_START, flag="--rebuilt-note (the header note paragraph)")
        old = out_lines[s:e]
        new = opts.rebuilt_note.strip("\n").split("\n")
        rewrites.append({"line_in": s + 1, "old": "\n".join(old), "new": "\n".join(new),
                         "why": "the header names this rebuild and the record file"})
        out_lines[s:e] = new

    new_text = "\n".join(out_lines)

    # 7. Prove it.
    before, after = _GEN.derive(text), _GEN.derive(new_text)
    for key in ("live_total", "population_live", "audience_live"):
        if before[key] != after[key]:
            raise Refused(f"{key} moved: {before[key]!r} -> {after[key]!r}; nothing written")
    if _GEN.live_member_ids(text) != _GEN.live_member_ids(new_text):
        raise Refused("the set of live member ids moved; nothing written")
    want_sections = [n for n in before["sections"] if n not in opts.drop_class_sections]
    if list(after["sections"]) != want_sections:
        raise Refused(f"class sections after the cut {list(after['sections'])} are not the input's "
                      f"minus the dropped ones {want_sections}")
    # The file-wide proof: every live id in every table, minus the rows inside
    # a dropped block or class section, must come through -- and nothing new.
    dropped_ranges = {j for j, g in removed.items() if g.startswith(("block:", "section:"))}
    expected = live_table_ids(lines, skip=dropped_ranges)
    actual = live_table_ids(out_lines)
    lost, gained = sorted(expected - actual), sorted(actual - expected)
    if lost or gained:
        raise Refused(f"live ids outside the dropped ranges moved: lost {lost[:12]}{'…' if len(lost) > 12 else ''}, "
                      f"gained {gained[:12]}; nothing written")
    report["live_table_ids"] = {"before": len(expected), "after": len(actual)}
    left = classify_struck_rows(out_lines)
    if left:
        raise Refused(f"{len(left)} struck row(s) survived the cut at lines {sorted(j + 1 for j in left)}")
    for j in removed:
        if lines[j].startswith(_FENCE):
            raise Refused(f"line {j + 1} opens with the payload fence {_FENCE!r}; it cannot be recorded verbatim")

    # 8. Regenerate the derived regions with the probe reader answering the
    #    roster. Each literal repair is a line that left the file too, so it is
    #    recorded as a rewrite: the payload is complete, not just the deletions.
    pre = new_text.split("\n")
    new_text, residual = _ASM.regenerate_regions(new_text, probe_ids)
    report["residual_drift"] = residual
    if residual:
        raise Refused("the cut ledger does not converge: " + "; ".join(
            f"[{d['region']}] {d['detail']}" for d in residual))
    post = new_text.split("\n")
    if len(pre) != len(post):
        raise Refused("the region regeneration changed the line count; nothing written")
    for i, (a, b) in enumerate(zip(pre, post)):
        if a != b:
            rewrites.append({"line_in": i + 1, "old": a, "new": b, "why": "derived region regenerated"})

    # 9. Pointers a surviving line still carries to what left.
    toks = _pointer_tokens(opts)
    for i, ln in enumerate(post, 1):
        for tok in toks:
            if tok in ln and _POINTER_WORDS.search(ln):
                report["pointers_to_review"].append({"line_out": i, "names": tok, "text": ln[:160]})
                break

    report["lines_out"] = len(post)
    report["lines_removed"] = len(removed)
    report["live_before"], report["live_after"] = before["live_total"], after["live_total"]
    report["population_live"], report["audience_live"] = after["population_live"], after["audience_live"]
    report["sections_before"], report["sections_after"] = len(before["sections"]), len(after["sections"])
    report["headings_that_lost_rows"] = sorted({
        _heading_of(lines, j) for j, g in removed.items() if g.startswith("row:")
    })
    return Result(text=new_text, payload=_payload(lines, removed, moved, rewrites, opts.date), report=report)


def _payload(lines: list[str], removed: dict[int, str], moved: list[tuple[str, list[int]]],
             rewrites: list[dict[str, object]], date: str) -> str:
    groups: dict[str, list[int]] = {}
    for j, g in sorted(removed.items()):
        groups.setdefault(g, []).append(j)
    md = [f"# Cut from the forward ledger on {date} -- record-branch payload", "",
          "_Generated by `scripts/ledger_structural_cut.py`. RECORD SURFACE -- do not edit, "
          "re-anchor or re-count. Every block, row and paragraph below left the working file "
          "verbatim; the whole pre-rebuild file is beside this one on the record branch._", ""]
    blocks = [g for g in groups if g.startswith("block:")]
    sections = [g for g in groups if g.startswith("section:")]
    paras = [g for g in groups if g.startswith("paragraph:")]
    rows = [g for g in groups if g.startswith("row:")]

    def emit(title: str, keys: list[str]) -> None:
        md.append(f"## {title} ({len(keys)})")
        md.append("")
        for g in keys:
            md.append(f"### {g.split(':', 1)[1]} ({len(groups[g])} lines)")
            md.append("")
            md.append(_FENCE)
            md.extend(lines[j] for j in groups[g])
            md.append(_FENCE)
            md.append("")

    emit("Blocks cut", blocks)
    emit("Class sections cut", sections)
    emit("Paragraphs cut", paras)
    emit("Rows dropped, by table", rows)
    md.append(f"## Blocks moved under the contract ({len(moved)})")
    md.append("")
    for title, js in moved:
        md.append(f"- `{title}` -- {len(js)} lines, headings demoted one level")
    md.append("")
    md.append(f"## Rewrites ({len(rewrites)})")
    md.append("")
    for r in rewrites:
        md.append(f"### line {r['line_in']} -- {r['why']}")
        md.append("")
        md.append(_FENCE)
        md.append(str(r["old"]))
        md.append(_FENCE)
        md.append("became")
        md.append(_FENCE)
        md.append(str(r["new"]))
        md.append(_FENCE)
        md.append("")
    return "\n".join(md) + "\n"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", required=True, type=Path, help="the rebuilt FORWARD_LEDGER (never the live one)")
    ap.add_argument("--probes", required=True, type=Path, help="its probes file (read, never written)")
    ap.add_argument("--out", required=True, type=Path, help="output directory (refused if it already holds a cut)")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD; names the payload")
    ap.add_argument("--strike-id", action="append", default=[], metavar="ID",
                    help="strike ID in the one non-class table row that carries it unstruck, before the cut (repeatable)")
    ap.add_argument("--drop-h2", action="append", default=[], metavar="PREFIX",
                    help="drop every h2 block whose title starts with PREFIX (repeatable; must match)")
    ap.add_argument("--move-h2-into-contract", action="append", default=[], metavar="TITLE",
                    help="move the h2 block TITLE to the end of the contract section, demoted (repeatable)")
    ap.add_argument("--drop-paragraph", action="append", default=[], metavar="START",
                    help="drop the one paragraph opening with START (repeatable)")
    ap.add_argument("--drop-class-section", action="append", default=[], metavar="§CN",
                    help="drop the all-struck class section and its class-index row (repeatable)")
    ap.add_argument("--rebuilt-note", type=Path, help="file whose text replaces the header note paragraph")
    ap.add_argument("--dry-run", action="store_true", help="print the report; write nothing")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)

    if not _DATE.match(args.date):
        print(f"--date must be YYYY-MM-DD, got {args.date!r}", file=sys.stderr)
        return 2
    try:
        text = args.ledger.read_text(encoding="utf-8")
        probes = _ASM.load_probes(json.loads(args.probes.read_text(encoding="utf-8")), args.probes.name)
        note = args.rebuilt_note.read_text(encoding="utf-8") if args.rebuilt_note else None
    except (OSError, ValueError) as exc:  # strict decode: a structured answer
        print(f"ledger_structural_cut: {exc}", file=sys.stderr)
        return 2
    probe_ids = {p.get("id") for p in probes.get("probes", []) if p.get("id")}
    outputs = (OUTPUT_LEDGER, f"cut-{args.date}.md", OUTPUT_REPORT)
    existing = [n for n in outputs if (args.out / n).exists()]
    if existing:
        # In --dry-run too: a rehearsal that reports success where the real
        # run would refuse is a rehearsal of nothing.
        print(f"ledger_structural_cut: {args.out} already holds a cut ({', '.join(existing)}); "
              "use a fresh --out", file=sys.stderr)
        return 3
    opts = Options(date=args.date, drop_h2=args.drop_h2, move_h2_into_contract=args.move_h2_into_contract,
                   drop_class_sections=args.drop_class_section, drop_paragraphs=args.drop_paragraph,
                   strike_ids=args.strike_id, rebuilt_note=note)
    try:
        result = cut(text, probe_ids, opts)
    except Refused as exc:
        print(f"ledger_structural_cut: REFUSED -- {exc}", file=sys.stderr)
        return 2
    rep = result.report
    if args.json:
        print(json.dumps(rep, indent=1, ensure_ascii=False))
    else:
        rd = rep["rows_dropped"]
        print(f"cut: {rep['lines_in']} -> {rep['lines_out']} lines; live {rep['live_before']} -> {rep['live_after']}; "
              f"live table ids {rep['live_table_ids']['before']} -> {rep['live_table_ids']['after']}; "
              f"rows dropped class {len(rd['class'])} / table {len(rd['table'])} / appendix-b {len(rd['appendix-b'])}; "
              f"blocks {len(rep['blocks_dropped'])} dropped, {len(rep['blocks_moved'])} moved; "
              f"paragraphs {len(rep['paragraphs_dropped'])}; class sections {rep['class_sections_dropped']}; "
              f"sections {rep['sections_before']} -> {rep['sections_after']}; struck ids {rep['strike_ids']}")
        for h in rep["headings_that_lost_rows"]:
            print(f"  typed count to review: {h}")
        for p in rep["pointers_to_review"]:
            print(f"  pointer to review (line {p['line_out']}, names {p['names']}): {p['text'][:100]}")
        for k in rep["struck_rows_kept_in_crosswalks"]:
            print(f"  struck crosswalk row kept (line {k['line_in']}): {k['text'][:100]}")
    if args.dry_run:
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    _GEN._atomic_write(args.out / OUTPUT_LEDGER, result.text)
    _GEN._atomic_write(args.out / f"cut-{args.date}.md", result.payload)
    _GEN._atomic_write(args.out / OUTPUT_REPORT, json.dumps(rep, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {args.out / OUTPUT_LEDGER}, {args.out / f'cut-{args.date}.md'}, {args.out / OUTPUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
