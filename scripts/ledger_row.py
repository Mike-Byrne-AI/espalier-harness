#!/usr/bin/env python3
"""Strike or file one forward-ledger row, with every mechanical companion step.

Why this exists
---------------
Closing a row is five edits that must agree: the member row is rewritten with
its PRIOR TEXT kept, the Appendix B index row is struck, the row's probe is
retired (a probe left behind cries wolf forever -- 14 of 198 did on
2026-09-02), the probe count moves, and the derived regions are regenerated.
Filing a row is the same five in the other direction plus one rule that is
easy to skip by hand: the new row's probe must be DRIVEN at filing and print
its ``open_value``. Every close this month was a hand-written Python block
doing these by feel. This script does them by construction, on the same
parsers ``generate_ledger_regions.py`` and ``check_ledger_probes.py`` already
own, and refuses to write anything unless the finished ledger converges.

Usage::

    # close a row: the closing text (between "CLOSED <date> — " and
    # "PRIOR TEXT:") comes from a file, so it can be long
    python3 scripts/ledger_row.py strike DEF-695 --text-file /tmp/695.md
    python3 scripts/ledger_row.py strike DEF-695 --text-file /tmp/695.md --anchor "new::anchor"

    # file a row after an existing one in the same section; the probe is run
    # first and must print --open-value, or nothing is written
    python3 scripts/ledger_row.py file DEF-697 --section C49 --after DEF-695 \\
        --anchor "tools/cc/hooks/_bash_patterns.py (no PowerShell permission extractor)" \\
        --text-file /tmp/697.md --severity minor \\
        --probe-cmd "python3 -c \\"...\\"" --open-value "attrib_allows=True" \\
        --subject tools/cc/hooks/_bash_patterns.py

    # re-pin a live row whose measured value moved (the hand pass a
    # STRIKE_CANDIDATE asks for when the verdict is "still open, the number
    # moved"): the probe is driven first and must print the NEW value
    python3 scripts/ledger_row.py repin DEF-665 --open-value 39 \
        --reason "pyproject still caps at 60 s; count moved 31 -> 39" [--text-file /tmp/665.md]

    # any verb: --dry-run prints the rows it would write and touches nothing;
    # --reconcile-count accepts a probe file whose _count disagrees with its
    # rows (a hand edit's only trace -- every verb refuses on one otherwise)

Exit codes: 0 written (or dry run); 2 refused (row not found, probe did not
print its open value, ledger would not converge, an in-flight pack's Scope (out)
still defers into the row or the section it empties) with the reason on stderr.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[1]
_SCRIPTS = _HERE.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _member_line(rid: str, text: str, *, struck_ok: bool) -> tuple[int, str] | None:
    """``(line_index, line)`` of the MEMBER row whose id cell carries ``rid``
    (second cell is a source site, never the bare ``§CN`` of an index row).
    Unstruck only unless ``struck_ok``.

    The cell may carry more than one id (``| `DEF-539` `LG-6` | ...``, three ids
    in ``DEF-371a``'s). Until 2026-09-20 this
    demanded a lone id before the pipe, so every verb refused such a row by
    EITHER id and seven of the eight carried probes nothing could stamp
    (``DEF-863``). The cell is read by the grammar's own reader, so any of its
    ids addresses the row; a strike closes the whole cell (see ``strike``)."""
    pat = re.compile(r"^\|[^\n]*`" + re.escape(rid) + r"`[^\n]*$", re.M)
    for m in pat.finditer(text):
        line = m.group(0)
        if rid not in _GEN.cell_ids(line):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)]
        if len(cells) > 2 and re.fullmatch(r"§C\d+", cells[2]):
            continue
        if _GEN._is_struck(line) and not struck_ok:
            continue
        return text[: m.start()].count("\n"), line
    return None


def _half_struck(rid: str, line: str) -> str | None:
    """The refusal when ``line``'s id cell is struck on some ids and not others,
    else None. Strike state is read at row level and a strike rewrites the
    whole cell, so a verb meeting this shape would close a live co-id as
    collateral or re-pin a closed one (code review of `DEF-863`, 2026-09-20;
    no such row exists today, so this is a refusal, not a repair)."""
    if _GEN.half_struck(line):
        return (f"{rid}'s id cell is struck on some ids and not others ({line[:60]!r}); "
                "a verb closes or re-pins the whole cell -- repair the cell by hand first")
    return None


def _index_line(rid: str, text: str) -> tuple[int, str] | None:
    pat = re.compile(r"^\|\s*(~~)?`" + re.escape(rid) + r"`(~~)?\s*\|\s*§C\d+\s*\|.*$", re.M)
    m = pat.search(text)
    if not m:
        return None
    return text[: m.start()].count("\n"), m.group(0)


_SEVERITIES = frozenset({"blocker", "major", "minor", "nit"})
_GEN = _load("generate_ledger_regions")  # the grammar's one home: vocabularies too
_CHK = _load("check_ledger_probes")  # the hashes' one home: the reader defines the pin
_CPL = _load("check_pack_landing")  # the packs' one home: the Scope (out) reader and the active population


class RowShape(Exception):
    """A member row this script cannot round-trip; the caller refuses."""


def _cells(line: str) -> list[str]:
    r"""The four cells of a §2 member row: ``| id | site | text | severity |``.

    Splits on UNESCAPED pipes only (the ledger escapes a literal pipe as
    ``\|``) and refuses any other shape: a three-cell row from another table,
    or a row whose text carries an unescaped pipe (five cells) -- the first
    cut took "the last pipe from the right" as the severity delimiter and, on
    the real ledger, moved 1,194 characters of one row into its severity
    column and raised on 28 three-cell rows (both red teams, driven).
    Refusing is the only safe answer: a mis-split strike rewrites the row.
    """
    body = line.strip()
    if not (body.startswith("|") and body.endswith("|")):
        raise RowShape(f"not a table row: {line[:120]!r}")
    cells = [c.strip() for c in re.split(r"(?<!\\)\|", body[1:-1])]
    if len(cells) not in (4, 6):
        raise RowShape(
            f"row has {len(cells)} cells, not 4 (id | site | text | severity) or 6 (... | "
            f"population | audience, the MIXED-class shape); a literal pipe in the text must "
            f"be escaped as \\| -- strike this one by hand: {line[:100]!r}"
        )
    if cells[3].lower() not in _SEVERITIES:
        raise RowShape(
            f"cell 4 {cells[3][:40]!r} is not a severity ({sorted(_SEVERITIES)}); "
            f"this is not a §2 member row: {line[:100]!r}"
        )
    if len(cells) == 6 and (cells[4] not in _GEN.POPULATIONS or cells[5] not in _GEN.AUDIENCES):
        raise RowShape(
            f"cells 5-6 {cells[4]!r} | {cells[5]!r} are not a population "
            f"({_GEN.POPULATIONS}) and an audience ({_GEN.AUDIENCES}): {line[:100]!r}"
        )
    return cells


def _pins(line: str) -> dict[str, str]:
    """Both pins the checker recomputes, from the checker's own functions."""
    return {"row_sha": _CHK.row_sha(line), "text_sha": _CHK.text_sha(line)}


def _mixed_tags(text: str, section: str) -> tuple[str | None, str | None] | None:
    """``section``'s class-index ``(population, audience)`` when EITHER axis is
    MIXED, else None. The generator reads a row's OWN cell on a MIXED axis and
    the class tag on a classed one (`derive`, the contradiction arm), so every
    row in such a class carries the 6-cell shape and its classed cell must
    repeat the class tag. Until 2026-09-20 this keyed on BOTH axes being MIXED
    (§C0's shape) -- already wrong on the live ledger, where four classes
    (§C13, §C14, §C18, §C20 as of 2026-09-20) are MIXED on audience alone
    (`DEF-776`), and wrong for ten in the third rebuild's file, whose §C1 is
    `OPERATOR_ACTION / MIXED`: there the both-axes test filed the 4-cell shape,
    refused only by convergence after the probe run, with the generator's dump
    instead of a refusal the verb owns. A placeholder class cell (`-`) reads
    None on its axis; no row cell there can be counted until the class is tagged."""
    tags = _GEN.declared_class_tags(text).get(section)
    if tags is None or _GEN.MIXED not in tags:
        return None
    return tags


def _classed_axis_mismatch(tags: tuple[str | None, str | None], population: str | None,
                           audience: str | None) -> str | None:
    """The refusal when a row's cell on a CLASSED axis differs from the class
    tag (the generator counts the class and names the row's cell), else None."""
    for label, ctag, given in (("population", tags[0], population), ("audience", tags[1], audience)):
        if ctag == _GEN.MIXED or given is None:
            continue
        if ctag is None:
            return (f"carries no {label} tag in its class index (a placeholder cell), so no row "
                    f"cell on that axis can be counted -- tag the class first")
        if given != ctag:
            return (f"declares {label} {ctag!r} in its class index, so a row there carries "
                    f"{ctag!r} on that axis, not {given!r} -- re-tag the class, or move the row")
    return None


def _section_holding(text: str, rid: str) -> str | None:
    """The ``§CN`` whose section physically holds ``rid``'s member row, read
    with the generator's own placement parser (``ledger_sections``) -- never
    from the Appendix B index row, a second oracle for the same fact that can
    disagree with placement between a hand row-move and the next suite run
    (failure-mode pass, 2026-09-20: a check keyed on the index row validated a
    row against the wrong class and told the operator to re-tag that class)."""
    for name, rows in _GEN.ledger_sections(text).items():
        if any(rid in _GEN.cell_ids(r) for r in rows):
            return name
    return None


def _mixed_axes_phrase(tags: tuple[str | None, str | None]) -> str:
    return ("both axes" if tags == (_GEN.MIXED, _GEN.MIXED)
            else f"one axis ({tags[0]} / {tags[1]})")


def _converge(gen, text: str, probes_path: Path) -> tuple[str, list[dict]]:
    gen._PROBES = probes_path
    drift = gen.find_drift(text)
    text, _n = gen.apply_writable(text, drift)
    gen._PROBES = probes_path
    return text, gen.find_drift(text)


def _commit_both(gen, *, ledger: Path, probes: Path, new_text: str, data: dict,
                 what: str) -> int:
    """Converge against the NEW probe roster held in a sidecar, then write the
    ledger and the probes together -- or neither. The first cut wrote the probe
    file before checking convergence, so a refused strike still retired the
    probe and left an open row with no probe: the exact "cries wolf, or never
    barks" state the roster rule exists to prevent (failure-mode pass, driven)."""
    sidecar = probes.with_name(probes.name + ".pending")
    sidecar.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        new_text, drift = _converge(gen, new_text, sidecar)
        if drift:
            print(f"ledger_row: the ledger would not converge after the {what}; nothing written:",
                  file=sys.stderr)
            for d in drift:
                print(f"  {d}", file=sys.stderr)
            return 2
        gen._atomic_write(ledger, new_text)
        sidecar.replace(probes)
        return 0
    finally:
        if sidecar.exists():
            sidecar.unlink()


def _load_probes(probes: Path, *, reconcile: bool) -> dict | None:
    """The probe roster, or None (reason on stderr) when its ``_count`` disagrees
    with the rows it carries and ``--reconcile-count`` was not given.

    The mismatch is ``check_ledger_probes``' tripwire -- it refuses every report
    on one, and that refusal is how DEF-711's stale pin was found. This writer
    cannot create the drift (it re-derives ``_count`` on every write), so a
    mismatch on load is always a HAND edit, and repairing it silently would
    destroy the one trace a hand edit leaves. The first cut of the unconditional
    write did exactly that (failure-mode pass, 2026-09-08): say the two numbers,
    stop, and let the operator confirm with the flag.
    """
    data = json.loads(probes.read_text(encoding="utf-8"))
    declared = data.get("_count")
    carried = len(data["probes"])
    if isinstance(declared, int) and declared != carried:
        msg = (f"ledger_row: {probes.name} declares _count={declared} but carries "
               f"{carried} probe(s) -- rows were added or removed outside this script.")
        if not reconcile:
            print(msg + " Check the roster, then re-run with --reconcile-count to "
                  "re-derive the count; nothing written.", file=sys.stderr)
            return None
        print(msg + " Reconciled to the roster (--reconcile-count).", file=sys.stderr)
    return data


def _deferrals_into(ledger: Path, ids: list[str]) -> list[str]:
    """Scope (out) lines of the ACTIVE packs (the ledger's own ``task-packs/``
    root plus ``Deferred/``, read through ``check_pack_landing``) that still
    cite an id this strike closes.

    ``DEF-412a``: nothing read a pack's Scope (out) before a row was struck, so
    a section could be drained "as landed" while an in-flight pack's only
    description of its remainder said "deferred to §CN" -- and the deferral
    went with it (a landed pack's parked §2.3 remainder was the case). Scope (out)
    ONLY: a
    roadmap names the rows its lanes will strike in its Reach and
    Implementation, and reading the whole pack would refuse every strike that
    roadmap exists to make. Two spellings are read, because the live packs use
    both: the prefixed id anywhere in the line (``DEF-412`` never reads
    ``DEF-412a`` as itself), and the bare tail inside a backticked LIST of id
    tails -- ``(`736, 424b, 516, PR-3, 6`)`` is how one active pack parks eleven
    rows, and the first cut read one of the eleven (both reviewers, 2026-09-21). A
    lone backticked number is not read: it is a count more often than a row,
    and the list may run across a line break. No ``§CN`` arm: class numbers
    were reissued at the 2026-09-20 rebuild, so a section number in a pack
    authored before it names the OLD section (a live roadmap cites §C16/§C18/§C49
    by the old numbers), and the structural cut owns section removal with its own
    refusals.
    """
    prefixed = [(i, re.compile(r"(?<![\w-])" + re.escape(i) + r"(?![\w-])")) for i in ids]
    tails = {i.split("-", 1)[1]: i for i in ids if "-" in i}
    id_shaped = re.compile(r"^(?:[A-Z]+-)?\d+[a-z]?$")
    packs_root = ledger.parent
    hits: list[str] = []
    for pack in _CPL.pack_files(_CPL.active_pack_dirs(packs_root)):
        text = pack.read_text(encoding="utf-8", errors="replace")
        blanked = _CPL.blank_fences(text)
        try:
            rel = pack.relative_to(packs_root.parent).as_posix()
        except ValueError:
            rel = pack.as_posix()
        for start, end in _CPL.scope_out_spans(text):
            body = blanked[start:end]
            base = text[:start].count("\n") + 1
            lines = body.split("\n")
            cited: dict[int, list[str]] = {}  # line number -> ids, first-seen order
            for n, line in enumerate(lines, start=base):
                for i, pat in prefixed:
                    if pat.search(line):
                        cited.setdefault(n, []).append(i)
            for m in re.finditer(r"`([^`]+)`", body):
                toks = [x for x in re.split(r"[,/\s]+", m.group(1)) if x]
                if len(toks) < 2 or not all(id_shaped.match(x) for x in toks):
                    continue
                n = base + body[: m.start()].count("\n")
                for x in toks:
                    hit = tails.get(x) or (x if x in ids else None)
                    if hit and hit not in cited.setdefault(n, []):
                        cited[n].append(hit)
            for n in sorted(cited):
                shown = lines[n - base].strip()[:140]
                hits.append(f"{rel}:{n}: {shown}  [cites {', '.join(cited[n])}]")
    return hits


def strike(rid: str, *, ledger: Path, probes: Path, text_file: Path, day: str,
           anchor: str | None, dry_run: bool, reconcile: bool = False,
           despite_deferrals: bool = False) -> int:
    gen = _load("generate_ledger_regions")
    text = ledger.read_text(encoding="utf-8")
    found = _member_line(rid, text, struck_ok=False)
    if found is None:
        print(f"ledger_row: no unstruck member row for {rid}", file=sys.stderr)
        return 2
    idx, line = found
    try:
        cells = _cells(line)
    except RowShape as exc:
        print(f"ledger_row: {exc}", file=sys.stderr)
        return 2
    if why := _half_struck(rid, line):
        print(f"ledger_row: {why}", file=sys.stderr)
        return 2
    # Every id the cell carries closes together -- the both-or-neither rule the
    # rebuild assembler enforces -- and each has its own Appendix B index row
    # and may own its own probe (`DEF-863`: the first cut rebuilt the cell from
    # the one id it was given, dropping the co-id from the struck row and
    # leaving its index row live and its probe crying wolf).
    ids = _GEN.cell_ids(line)
    closing = text_file.read_text(encoding="utf-8").strip().replace("\n", " ")
    struck_cell = " ".join(f"~~`{i}`~~" for i in ids)
    new_line = (f"| {struck_cell} | {anchor or cells[1]} | ✅ **CLOSED {day} — {closing}** "
                f"PRIOR TEXT: {cells[2]} | " + " | ".join(cells[3:]) + " |")
    lines = text.split("\n")
    lines[idx] = new_line
    index_state: dict[str, str] = {}  # per id: struck / already struck / not found
    for i in ids:
        ix = _index_line(i, "\n".join(lines))
        if ix is None:
            index_state[i] = "not found"
        elif "~~" in ix[1].split("|")[1]:
            index_state[i] = "already struck"
        else:
            j, il = ix
            if anchor:
                section = [c.strip() for c in il.split("|")][2]
                lines[j] = f"| ~~`{i}`~~ | {section} | {anchor} |"
            else:
                lines[j] = il.replace(f"`{i}`", f"~~`{i}`~~", 1)
            index_state[i] = "struck"
    new_text = "\n".join(lines)
    # The packs are read BEFORE anything is written and before the dry run
    # prints: a deferral into this row is a reason not to strike it, and the
    # dry run must show that refusal rather than a row it would never write.
    deferrals = _deferrals_into(ledger, ids)
    if deferrals:
        if not despite_deferrals:
            print(f"ledger_row: {len(deferrals)} Scope (out) line(s) in active packs still cite "
                  f"what this strike closes (DEF-412a):", file=sys.stderr)
            for h in deferrals:
                print(f"  {h}", file=sys.stderr)
            print("  Re-point or drop each citation in its pack (or record where the work went), "
                  "then strike; if this strike is the citing pack's OWN later phase, move the row "
                  "from its Scope (out) to its Landing first. --despite-deferrals strikes anyway, "
                  "and the closing text should then say where the deferred work went. "
                  "Nothing written.", file=sys.stderr)
            return 2
        print(f"ledger_row: striking despite {len(deferrals)} deferral(s) (--despite-deferrals):",
              file=sys.stderr)
        for h in deferrals:
            print(f"  {h}", file=sys.stderr)
    data = _load_probes(probes, reconcile=reconcile)
    if data is None:
        return 2
    before = len(data["probes"])
    data["probes"] = [p for p in data["probes"] if p["id"] not in ids]
    retired = before - len(data["probes"])
    data["_count"] = len(data["probes"])  # re-derived; a mismatch was refused or announced above
    index_note = (f"index row {index_state[rid]}" if len(ids) == 1
                  else "index rows: " + ", ".join(f"{i} {s}" for i, s in index_state.items()))
    if dry_run:
        print(new_line)
        print(f"({index_note}; {retired} probe(s) would retire)")
        return 0
    rc = _commit_both(gen, ledger=ledger, probes=probes, new_text=new_text, data=data, what="strike")
    if rc == 0:
        with_ids = f" (with {', '.join(i for i in ids if i != rid)})" if len(ids) > 1 else ""
        print(f"struck {rid}{with_ids}; {retired} probe(s) retired; regions converged")
    return rc


def file_row(rid: str, *, ledger: Path, probes: Path, section: str, after: str,
             anchor: str, index_anchor: str | None, text_file: Path, severity: str,
             probe_cmd: str, open_value: str, subject: str, why_not: str | None,
             day: str, dry_run: bool, root: Path, reconcile: bool = False,
             population: str | None = None, audience: str | None = None,
             inputs: list[str] | None = None) -> int:
    gen = _load("generate_ledger_regions")
    text = ledger.read_text(encoding="utf-8")
    if _member_line(rid, text, struck_ok=True) is not None:
        print(f"ledger_row: {rid} already has a member row", file=sys.stderr)
        return 2
    prev = _member_line(after, text, struck_ok=True)
    if prev is None:
        print(f"ledger_row: no member row for --after {after}", file=sys.stderr)
        return 2
    section = section if section.startswith("§") else f"§{section}"
    # --section selects the class whose tags the new row is validated against,
    # so it must be the section --after's row actually sits in: the row lands
    # after that row wherever it is, and a mis-sectioned row converges whenever
    # the two classes happen to agree (both reviewers drove it, 2026-09-20;
    # before the per-axis rule the hole reached §C0 only).
    holding = _section_holding(text, after)
    if holding != section:
        print(f"ledger_row: --after {after} sits in {holding or 'no class section'}, not "
              f"{section}; the row lands after it, so --section must name that section",
              file=sys.stderr)
        return 2
    body = text_file.read_text(encoding="utf-8").strip().replace("\n", " ")
    # A class MIXED on either axis carries the row's own population and
    # audience cells (the generator reads the row's cell on a MIXED axis and
    # the class tag on a classed one, so the classed cell must repeat it);
    # every other section inherits its class-index tags, and a row filed there
    # WITH cells would be counted by the class and printed by the row (both
    # reviewers, driven). So the pair is required exactly when the section is
    # MIXED on an axis and refused otherwise.
    class_tags = _mixed_tags(text, section)
    mixed = class_tags is not None
    if mixed and not (population and audience):
        axes = _mixed_axes_phrase(class_tags)
        need = " and ".join(
            f"{flag} {ctag}" if ctag not in (None, _GEN.MIXED)
            else (f"{flag} one of {vocab}" if ctag == _GEN.MIXED
                  else f"{flag} (the class index carries no tag on this axis -- tag the class first)")
            for flag, ctag, vocab in (("--population", class_tags[0], _GEN.POPULATIONS),
                                      ("--audience", class_tags[1], _GEN.AUDIENCES))
        )
        print(f"ledger_row: {section} is MIXED on {axes}; give {need}", file=sys.stderr)
        return 2
    if not mixed and (population or audience):
        print(f"ledger_row: {section} inherits its tags from the class index; a row filed "
              "there must not carry its own", file=sys.stderr)
        return 2
    if mixed and (why := _classed_axis_mismatch(class_tags, population, audience)):
        print(f"ledger_row: {section} {why}", file=sys.stderr)
        return 2
    tags = f" {population} | {audience} |" if mixed else ""
    new_line = f"| `{rid}` | {anchor} | {body} | {severity} |{tags}"
    new_index = f"| `{rid}` | {section} | {index_anchor or anchor} |"
    # the probe is driven BEFORE anything is written: a filed row's claim must
    # be re-derivable from the day it is filed
    if why_not is None:
        # run the probe through the checker's OWN runner -- same argv split,
        # same cwd, same timeout, same three-way verdict -- so a probe accepted
        # here is by construction one the recurring check can run (the first
        # cut shelled out itself from the ledger file's grandparent with a 10x
        # timeout; failure-mode pass)
        checker = _load("check_ledger_probes")
        checker._ROOT = root
        # `inputs` rides along: the recurring check reads it through the same
        # gate, so a declared path absent here refuses the filing the way it
        # would UNRESOLVE the row later (DEF-858).
        verdict, detail = checker.run_probe(
            {"cmd": probe_cmd, "open_value": open_value, "subject": subject, "why_not": None,
             "inputs": inputs}
        )
        if verdict != checker.STILL_OPEN:
            print(f"ledger_row: the probe does not print its open value {open_value!r} "
                  f"({verdict}: {detail}); nothing filed", file=sys.stderr)
            return 2
    lines = text.split("\n")
    lines.insert(prev[0] + 1, new_line)
    ix = _index_line(after, "\n".join(lines))
    if ix is not None:
        lines.insert(ix[0] + 1, new_index)
    new_text = "\n".join(lines)
    entry = {"id": rid, "subject": subject,
             "cmd": None if why_not is not None else probe_cmd,
             "open_value": None if why_not is not None else open_value,
             "why_not": why_not,
             # written only when declared: an entry that reads nothing beyond
             # its subject keeps the shape every existing entry has
             **({"inputs": inputs} if inputs is not None else {}),
             **_pins(new_line),
             f"verified_{day.replace('-', '_')}": f"OPEN (filed {day}; probe driven at filing)"}
    if dry_run:
        print(new_line); print(new_index); print(json.dumps(entry, indent=1))
        return 0
    data = _load_probes(probes, reconcile=reconcile)
    if data is None:
        return 2
    data["probes"].append(entry)
    data["_count"] = len(data["probes"])  # re-derived; see _load_probes
    rc = _commit_both(gen, ledger=ledger, probes=probes, new_text=new_text, data=data, what="filing")
    if rc == 0:
        print(f"filed {rid} after {after} in {section}; probe added (row_sha {entry['row_sha']}); regions converged")
    return rc


def repin(rid: str, *, ledger: Path, probes: Path, open_value: str | None, reason: str,
          text_file: Path | None, anchor: str | None, probe_cmd: str | None, day: str,
          dry_run: bool, root: Path, reconcile: bool = False,
          population: str | None = None, audience: str | None = None,
          severity: str | None = None, subject: str | None = None,
          inputs: list[str] | None = None) -> int:
    """Re-pin a LIVE row whose measured value moved off its ``open_value``.

    The hand pass a STRIKE_CANDIDATE verdict asks for ends one of two ways:
    the row is struck, or it is still open and the number moved. This is the
    second: drive the probe FIRST (the checker's own runner) and require it to
    print the NEW value, rewrite the cells that were asked for, recompute
    ``row_sha`` from the rewritten line, stamp ``verified_<day>`` with the
    reason, and converge the regions -- or write nothing. By hand this was
    five edits that agreed by luck; on 2026-09-08 a by-hand pass spliced two
    Appendix B rows into one line (the completeness gate caught it) and
    re-pinned five values that nothing but the pinner had witnessed
    (failure-mode pass). A verb can require the reason; a hand cannot.
    """
    gen = _load("generate_ledger_regions")
    text = ledger.read_text(encoding="utf-8")
    found = _member_line(rid, text, struck_ok=False)
    if found is None:
        print(f"ledger_row: no unstruck member row for {rid}", file=sys.stderr)
        return 2
    idx, line = found
    try:
        cells = _cells(line)
    except RowShape as exc:
        print(f"ledger_row: {exc}", file=sys.stderr)
        return 2
    if why := _half_struck(rid, line):
        print(f"ledger_row: {why}", file=sys.stderr)
        return 2
    data = _load_probes(probes, reconcile=reconcile)
    if data is None:
        return 2
    entry = next((p for p in data["probes"] if p.get("id") == rid), None)
    if entry is None:
        print(f"ledger_row: {rid} carries no probe to re-pin", file=sys.stderr)
        return 2
    cmd = probe_cmd or entry.get("cmd")
    new_value = open_value if open_value is not None else entry.get("open_value")
    if (subject or inputs) and not cmd:
        flag = "--subject" if subject else "--inputs"
        print(f"ledger_row: {rid} has no probe command, so {flag} cannot be driven; give "
              f"--probe-cmd and --open-value with it (code review, 2026-09-21: the first cut "
              f"wrote an undriven subject and stamped STILL_OPEN)", file=sys.stderr)
        return 2
    if cmd:
        if not new_value:
            print(f"ledger_row: {rid} has a probe command; give --open-value", file=sys.stderr)
            return 2
        checker = _load("check_ledger_probes")
        checker._ROOT = root
        verdict, detail = checker.run_probe(
            {"cmd": cmd, "open_value": new_value, "subject": subject or entry.get("subject"),
             "why_not": None,
             # the declaration the recurring check will read -- new or kept --
             # is driven here too, so a member absent on this tree refuses the
             # re-pin instead of stamping STILL_OPEN over an UNRESOLVED (DEF-858)
             "inputs": inputs if inputs is not None else entry.get("inputs")}
        )
        if verdict != checker.STILL_OPEN:
            print(f"ledger_row: the probe does not print the new open value {new_value!r} "
                  f"({verdict}: {detail}); nothing re-pinned", file=sys.stderr)
            return 2
    if text_file is not None:
        cells[2] = text_file.read_text(encoding="utf-8").strip().replace("\n", " ")
    if anchor:
        cells[1] = anchor
    if population or audience:
        # Re-classification is a live operation (a class-index cell already
        # reads "re-derived 2026-09-05; was ADOPTER"); without a verb it was a
        # hand edit that staled row_sha and trained the reader to discount
        # STALE_CLAIM (reflect pass + failure-mode pass, 2026-09-08).
        section_of_row = _section_holding(text, rid)
        if section_of_row is None:
            print(f"ledger_row: {rid}'s member row sits under no class-section heading, so its "
                  "class tags cannot be read; move the row into a class section first", file=sys.stderr)
            return 2
        class_tags = _mixed_tags(text, section_of_row)
        if class_tags is None:
            print(f"ledger_row: {rid} inherits its tags from the class index; re-tag the "
                  "class, or move the row to a MIXED class", file=sys.stderr)
            return 2
        # A class MIXED on one axis keeps its classed axis: retagging that cell
        # would print one token while the class counts another. The generator
        # catches it too, but only after the probe run and the sidecar write,
        # as a convergence dump rather than a refusal the verb owns (both
        # reviewers, 2026-09-20). Refuse it here, by name.
        if (why := _classed_axis_mismatch(class_tags, population, audience)):
            print(f"ledger_row: {rid} sits in {section_of_row}, which {why}", file=sys.stderr)
            return 2
        if len(cells) != 6:
            # The row predates its class going MIXED (a rebuild flips classes),
            # and a row left 4-cell in a MIXED-axis class strands EVERY verb on
            # the whole ledger, because convergence is global (failure-mode
            # pass, 2026-09-20). Widen it in place when both cells are given;
            # otherwise name the remedy instead of the classed-section refusal,
            # which pointed the wrong way.
            if not (population and audience):
                print(f"ledger_row: {section_of_row} is MIXED on {_mixed_axes_phrase(class_tags)} "
                      f"and {rid} still carries no tag cells; give --population and --audience "
                      "together to widen it", file=sys.stderr)
                return 2
            cells = cells[:4] + [population, audience]
        else:
            if population:
                cells[4] = population
            if audience:
                cells[5] = audience
    # Severity is cell 4 of EVERY member row -- the 4-cell class-tagged shape
    # and the 6-cell MIXED shape both carry it (`_is_member_row` keys on
    # exactly that), so unlike population/audience this needs no MIXED class
    # and no class re-tag. Until 2026-09-18 there was no verb for it at all:
    # `file` took --severity and `repin` did not, so a re-grade was a hand
    # edit of the one cell nothing derives, gates or gives a rubric -- and a
    # hand edit staled `row_sha`, flipping the row's own probe to STALE_CLAIM
    # while the grade itself went unwitnessed. The 2026-09-17 severity
    # re-audit measured the consequence: population and audience are derived,
    # gated, repinnable and advisory-checked; severity is none of the four,
    # and both rows that audit promoted had to wait on this leg.
    # `--reason` is already required on this verb, so a grade cannot move
    # here without its rationale attached.
    old_severity = cells[3]
    if severity:
        cells[3] = severity
    # cells[0] is the whole id cell, kept as it was: a co-id (`DEF-863`) stays
    # on the row. The anchor is the ROW's, so it moves on every id's index row;
    # the probe driven and stamped is the addressed id's alone -- a sibling's
    # probe is a different oracle nobody ran, and the verb names it below.
    new_line = "| " + " | ".join(cells) + " |"
    lines = text.split("\n")
    lines[idx] = new_line
    ids = _GEN.cell_ids(line)
    siblings = [i for i in ids if i != rid]
    if anchor:
        for i in ids:
            if (ix := _index_line(i, "\n".join(lines))) is not None:
                j, il = ix
                section = [c.strip() for c in il.split("|")][2]
                lines[j] = f"| `{i}` | {section} | {anchor} |"
    new_text = "\n".join(lines)
    old_value = entry.get("open_value")
    old_subject = entry.get("subject")
    old_inputs = entry.get("inputs")
    entry["cmd"] = cmd
    entry["open_value"] = new_value
    if inputs is not None:
        # The paths the command reads beyond its subject; driven above with the
        # rest of the probe. A hand edit of this list is the same trace-destroying
        # path a hand-moved subject was.
        entry["inputs"] = inputs
    if subject:
        # The subject is the file the fix EDITS, and the probe-shape ratchet
        # (tests/test_check_ledger_probes.py) reads it: a probe that names the
        # module it imports as its subject reads as counting vocabulary in its own
        # subject file (DEF-914 at filing, 2026-09-21). Moving it is a verb, not a
        # hand edit -- the new subject was driven above like any other field.
        entry["subject"] = subject
    if probe_cmd:
        entry["why_not"] = None
    entry.update(_pins(new_line))
    moved = f"{old_value!r} -> {new_value!r}" if new_value != old_value else "value unchanged"
    if severity and severity != old_severity:
        moved += f"; severity {old_severity} -> {severity}"
    if subject and subject != old_subject:
        moved += f"; subject {old_subject!r} -> {subject!r}"
    if inputs is not None and inputs != old_inputs:
        moved += f"; inputs {old_inputs!r} -> {inputs!r}"
    entry[f"verified_{day.replace('-', '_')}"] = (
        f"STILL_OPEN (re-pinned {moved} on {day}: {reason})"
    )
    data["_count"] = len(data["probes"])
    sibling_note = (f" (shares its row with {', '.join(siblings)}, whose probe(s) this verb did "
                    f"not drive -- repin each if the claim moved)") if siblings else ""
    if dry_run:
        print(new_line)
        if sibling_note:
            print(sibling_note.strip())  # its own line, before the entry: read once, not found after a 700-char dump
        print(json.dumps(entry, indent=1, ensure_ascii=False))
        return 0
    rc = _commit_both(gen, ledger=ledger, probes=probes, new_text=new_text, data=data, what="re-pin")
    if rc == 0:
        print(f"re-pinned {rid}: {moved}; row_sha {entry['row_sha']}; regions converged{sibling_note}")
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(_ROOT), help="repo root: the probe's cwd (default: this checkout)")
    ap.add_argument("--ledger", default=str(_ROOT / "task-packs" / "FORWARD_LEDGER.md"))
    ap.add_argument("--probes", default=str(_ROOT / "task-packs" / "LEDGER_PROBES.json"))
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reconcile-count", action="store_true",
                    help="accept a probe file whose _count disagrees with its rows and re-derive it "
                         "(every verb refuses on the mismatch otherwise: it is a hand edit's only trace)")
    sub = ap.add_subparsers(dest="verb", required=True)
    st = sub.add_parser("strike", help="close a row, keeping its PRIOR TEXT and retiring its probe")
    st.add_argument("rid")
    st.add_argument("--text-file", required=True, help="the closing text (after 'CLOSED <date> — ')")
    st.add_argument("--anchor", help="replace the site/anchor cell (default: keep)")
    st.add_argument("--despite-deferrals", action="store_true",
                    help="strike although an active pack's Scope (out) still defers into the row "
                         "or the section it empties (DEF-412a); the deferrals print as an advisory "
                         "and the closing text should say where the work went")
    fi = sub.add_parser("file", help="file a row after an existing one; its probe is driven first")
    fi.add_argument("rid")
    fi.add_argument("--section", required=True, help="class section, e.g. C49 or §C49")
    fi.add_argument("--after", required=True, help="the row id to insert after")
    fi.add_argument("--anchor", required=True)
    fi.add_argument("--index-anchor", help="Appendix B anchor (default: --anchor)")
    fi.add_argument("--text-file", required=True)
    fi.add_argument("--severity", required=True, choices=["blocker", "major", "minor", "nit"])
    fi.add_argument("--probe-cmd", help="one-liner that prints --open-value while the defect is open")
    fi.add_argument("--open-value")
    fi.add_argument("--subject", required=True, help="the probe's subject file")
    fi.add_argument("--inputs", action="append", metavar="PATH",
                    help="a path the probe's COMMAND reads beyond --subject (repeatable); a member "
                         "absent on a checkout makes the probe UNRESOLVED there, never a strike, "
                         "and the probe is driven with the list first")
    fi.add_argument("--why-not", help="declare the row unmeasurable instead of giving a probe")
    fi.add_argument("--population", choices=list(_GEN.POPULATIONS),
                    help="with --audience: the row's own tags (a section MIXED on either axis: §C0, or a one-axis-MIXED class where the classed cell must repeat the class tag)")
    fi.add_argument("--audience", choices=list(_GEN.AUDIENCES))
    rp = sub.add_parser("repin", help="re-pin a live row whose measured value moved; the probe is driven first")
    rp.add_argument("rid")
    rp.add_argument("--open-value", help="the value the probe prints now (default: keep)")
    rp.add_argument("--reason", required=True, help="why the value moved and the claim still stands")
    rp.add_argument("--text-file", help="replace the row's text cell (default: keep)")
    rp.add_argument("--anchor", help="replace the site/anchor cell, member and index rows (default: keep)")
    rp.add_argument("--probe-cmd", help="replace the probe command (default: keep)")
    rp.add_argument("--subject", help="re-point the probe's subject, the file the fix edits (default: keep); "
                                      "the probe is driven against it first")
    rp.add_argument("--inputs", action="append", metavar="PATH",
                    help="declare the paths the probe's command reads beyond its subject (repeatable; "
                         "replaces the list; default: keep); the probe is driven with them first")
    rp.add_argument("--population", choices=list(_GEN.POPULATIONS),
                    help="re-classify a row on an axis its class index marks MIXED (default: keep); "
                         "the classed axis is refused by name, and a row left 4-cell when its "
                         "class went MIXED is widened when both flags come together")
    rp.add_argument("--audience", choices=list(_GEN.AUDIENCES))
    rp.add_argument("--severity", choices=sorted(_SEVERITIES),
                    help="re-grade the row's severity (default: keep). Every member "
                         "row carries this cell, so no MIXED class is needed; --reason "
                         "is required on this verb and carries the grade's rationale")
    args = ap.parse_args(argv)
    ledger, probes = Path(args.ledger), Path(args.probes)
    if args.verb == "strike":
        return strike(args.rid, ledger=ledger, probes=probes, text_file=Path(args.text_file),
                      day=args.date, anchor=args.anchor, dry_run=args.dry_run,
                      reconcile=args.reconcile_count, despite_deferrals=args.despite_deferrals)
    if args.verb == "repin":
        return repin(args.rid, ledger=ledger, probes=probes, open_value=args.open_value,
                     reason=args.reason,
                     text_file=Path(args.text_file) if args.text_file else None,
                     anchor=args.anchor, probe_cmd=args.probe_cmd, subject=args.subject, day=args.date,
                     dry_run=args.dry_run, root=Path(args.root).resolve(),
                     reconcile=args.reconcile_count,
                     population=args.population, audience=args.audience,
                     severity=args.severity, inputs=args.inputs)
    if args.why_not is None and not (args.probe_cmd and args.open_value):
        ap.error("file: give --probe-cmd and --open-value, or --why-not")
    if args.why_not is not None and args.inputs:
        # `run_probe` returns NO_ORACLE before the inputs gate on a row with no
        # command, so a declaration written here would be undriven -- the shape
        # `repin` refuses by name (both reviewers, 2026-09-22).
        ap.error("file: --inputs cannot be driven on a row declared --why-not; drop one")
    if args.verb == "file" and bool(args.population) != bool(args.audience):
        ap.error("file: --population and --audience come together")
    return file_row(args.rid, ledger=ledger, probes=probes, section=args.section,
                    after=args.after, anchor=args.anchor, index_anchor=args.index_anchor,
                    text_file=Path(args.text_file), severity=args.severity,
                    probe_cmd=args.probe_cmd or "", open_value=args.open_value or "",
                    subject=args.subject, why_not=args.why_not, day=args.date,
                    dry_run=args.dry_run, root=Path(args.root).resolve(),
                    reconcile=args.reconcile_count,
                    population=args.population, audience=args.audience,
                    inputs=args.inputs)


if __name__ == "__main__":
    sys.exit(main())
