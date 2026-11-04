#!/usr/bin/env python3
"""What the SessionStart banner spent, start by start, read from one project's transcripts.

Why this exists
---------------
DEF-674 fitted the banner under ``_MAX_CONTEXT_CHARS`` (9,500 UTF-16 units of
the host's 10,000-unit cap on one hook context string), and the blueprint is
the one tenant ``tools/cc/hooks/session_start.py::_fit_banner`` shrinks to
make it fit. How often it yields, what it keeps and what the goal file costs it
are on the transcripts, since Claude Code records every hook context string it
hands the model. the banner pack's Task 0 reads its kill condition from this census,
never from a hand's count: the pack's two prototype runs counted the host's
spill previews as banners.

What it reads
-------------
Every ``*.jsonl`` directly under ``--project`` (one explicit directory, one
transcript per session; the subagent transcripts in the session folders carry
SubagentStart context and no banner, so they are not read), every record whose
``attachment.type`` is ``hook_additional_context``, and each string of its
``content`` list on its own. No record names its source (``hookName`` is
``SessionStart`` on a start, a resume and a compaction alike), so the kind is
read from the text:

* **whole**: opens ``=== Espalier-Harness === Session Start ===``;
* **spill**: that opening inside the host's ``<persisted-output>`` form, a
  banner past the host's cap that Claude Code saved to a file and replaced
  with its path and a 2,000-character preview;
* **compact**: opens ``=== Espalier-Harness === POST-COMPACTION RE-ORIENT``,
  and **compact spill**, that opening inside ``<persisted-output>``;
* **short**: the hook's own short banner (``SessionStart (short: ...``), which
  a start past its wall gives;
* a SessionStart string of none of these is counted as unclassified, never
  dropped, and every other hook's string (the PostToolUse advisories) as not
  a banner.

Per whole banner: the record's timestamp; the HEAD its ``Checkout:`` line
names (``now <sha>``) when it names one; its length in UTF-16 units
(``len(text.encode("utf-16-le")) // 2``, the hook's ``_units``), whole and
per section. A section opens at the line that starts with its header
(``SECTION_HEADERS``, in the order the hook renders them; a header line opens
its section only past the section the banner is in, so a goal file quoting an
earlier header is content), the text before the first is the header, and the
sections sum to the whole. The header's ``Blueprint:`` slot is measured alone
too (the text between ``Blueprint: `` and the ``Surface:`` line), which is the
yield line's kept figure whenever there is one. From the health section alone
(a goal file can quote a health line): the yield line's two figures (what the
loader handed in, what the banner kept) and the share; the ledger line's goal
bytes, its soft budget and the headroom; the body loss the "ceiling still
binds" line names. Whether the body ends with the body-cut marker (the hook
appends it where the kept body stops, right before the orientation tail, so a
goal file quoting it is not a clip), and whether the blueprint was cut to its
header line.

Before and since the ceiling: by date against DEF-674's merge to main
(``CEILING_MERGE``, PR #368 from ``lane/banner-fits-the-host-cap``, at
``CEILING_AT``; the lane's own commits are dated 2026-10-29, so a banner of the
29th or the 30th is before it), and by HEAD where the ``Checkout:`` line names
one, read as ``git merge-base --is-ancestor`` of the merge in ``--repo``:
since, before, or not in this clone (a worker's unpushed commit, another box's
history).

The ``--ranking`` table's last three columns are Task 0's arithmetic: the
blueprint's loss (handed in less kept), the goal's bytes past its soft budget,
and whether that excess plus the headroom covers the loss. Bytes are set
against units as the pack sets them: the banner is ASCII but for what a file
quotes.

Usage::

    python3 scripts/banner_census.py --project ~/.claude/projects/<project dir>
    python3 scripts/banner_census.py --project <dir> --last 20 --ranking
    python3 scripts/banner_census.py --project <dir> --json

Exit codes: 0 = report printed (a directory with no whole banner is a note);
2 = usage error, or a directory that cannot be read. Self-host dev tooling:
stdlib only, no import from ``tools/cc/`` or ``espalier/``, 7-bit ASCII out.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
HOOK_CONTEXT = "hook_additional_context"

#: The banner openings the kinds are read from (``tools/cc/hooks/session_start.py``:
#: the whole banner's and the re-orient's first header part, the short banners').
SESSION_START_OPENING = "=== Espalier-Harness === Session Start ==="
COMPACT_OPENING = "=== Espalier-Harness === POST-COMPACTION RE-ORIENT"
SHORT_OPENING = "=== Espalier-Harness === SessionStart (short:"
#: The host's spill form: a string past its cap, saved to a file, the path and
#: a preview in its place (docs/external/cc-hook-protocol.md, "Large-payload spill").
SPILL_OPENING = "<persisted-output>"

#: Module constants of the hook, carried as literals (no import from
#: tools/cc/); tests/test_banner_census.py pins each equal to the hook's own.
HEALTH_HEADER = "--- BANNER HEALTH ---"
GOAL_HEADER = (
    "--- GOAL / PROGRESS (cc/GOAL.md -- the LAST HANDOFF'S SNAPSHOT, not live "
    "state; re-derive any figure before relying on it) ---"
)
GOAL_HEADER_COMPACT = (
    "--- GOAL / PROGRESS [session-start SNAPSHOT -- live state is the plan + "
    "summary above] ---"
)
HEALTH_YIELD = "[banner] the blueprint yielded to fit the ceiling: "
HEALTH_BINDS = "[banner] the ceiling still binds: the body loses "
BODY_CUT_MARKER = "\n[banner body truncated -- budget]"
BLUEPRINT_HEAD_MARKER = " [cut to its header line to fit the ceiling]"
MAX_CONTEXT_CHARS = 9_500
HOST_CONTEXT_CAP_CHARS = 10_000

#: Headers the hook renders inline (literals or f-strings), carried as the
#: prefix every rendering shares; the test finds each in the hook's source.
#: MEMORY has three renderings and STANDING two on this box's transcripts (the
#: titled index before the count line), so each is its fixed head. The full
#: banner's WARNINGS and NOTES come from one f-string, ``--- {title} ---``.
MEMORY_HEADER = "--- MEMORY"
STANDING_HEADER = "--- STANDING PRINCIPLES"
FOOTGUNS_HEADER = "--- FOOTGUNS & FAILURE MODES (pull, don't scan) ---"
WARNINGS_HEADER = "--- WARNINGS ---"
NOTES_HEADER = "--- NOTES ---"
OPEN_PLAN_HEADER = "--- OPEN PLAN ("
ORIENTATION_HEADER = "Orientation (on first response"
BLUEPRINT_LINE = "Blueprint: "
SURFACE_LINE = "Surface:   "

#: The sections in the order the hook renders them: the header, then the body
#: (the health block first, the warnings, an open plan, the goal, the memory
#: digest, the standing index, the footguns pointer; the stop-gate dormancy
#: note has no header and counts in the footguns section), then the tail.
SECTIONS = ("header", "health", "warnings", "notes", "open_plan", "goal", "memory", "standing", "footguns",
            "orientation")
SECTION_HEADERS = (
    ("health", HEALTH_HEADER),
    ("warnings", WARNINGS_HEADER),
    ("notes", NOTES_HEADER),
    ("open_plan", OPEN_PLAN_HEADER),
    ("goal", GOAL_HEADER),
    ("goal", GOAL_HEADER_COMPACT),
    ("memory", MEMORY_HEADER),
    ("standing", STANDING_HEADER),
    ("footguns", FOOTGUNS_HEADER),
    ("orientation", ORIENTATION_HEADER),
)
KINDS = ("whole", "spill", "compact", "compact_spill", "short", "unclassified", "not_banner")

#: DEF-674's merge to main: PR #368, lane/banner-fits-the-host-cap.
CEILING_MERGE = "970a64640c52f85685a12f844e01080c4ef0856c"
CEILING_AT = "2026-10-31T07:14:28Z"
GIT_TIMEOUT = 10

HEAD_RE = re.compile(r"^Checkout:\s.*?\bnow ([0-9a-f]{7,40})\b", re.M)
YIELD_RE = re.compile(re.escape(HEALTH_YIELD) + r"(\d+) -> (\d+) characters \(its share (\d+)\)")
LEDGER_RE = re.compile(r"^\[banner\] \d+ characters of the host's \d+: header .*$", re.M)
GOAL_RE = re.compile(r"\bgoal (\d+)(?: of (\d+))? bytes")
HEADROOM_RE = re.compile(r"\bheadroom (-?\d+)")
BINDS_RE = re.compile(re.escape(HEALTH_BINDS) + r"(\d+) characters")


def units(text: str) -> int:
    """``text``'s length as the host counts it: UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def parse_stamp(stamp: object) -> Optional[datetime]:
    """A record's ISO timestamp as an aware UTC datetime, or None."""
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def short_stamp(stamp: Optional[str]) -> str:
    at = parse_stamp(stamp)
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if at else "-"


def kind_of(text: str, hook: object) -> str:
    """The kind of one context string, read from its text."""
    if text.startswith(SESSION_START_OPENING):
        return "whole"
    if text.startswith(COMPACT_OPENING):
        return "compact"
    if text.startswith(SHORT_OPENING):
        return "short"
    if text.startswith(SPILL_OPENING):
        if SESSION_START_OPENING in text:
            return "spill"
        if COMPACT_OPENING in text:
            return "compact_spill"
    return "unclassified" if hook == "SessionStart" else "not_banner"


def split_sections(text: str) -> dict:
    """``text`` cut at the lines that open each section, in the hook's order:
    {section: its text}, the sections present alone; their texts join to ``text``."""
    rank = {name: i for i, name in enumerate(SECTIONS)}
    out: dict = {"header": []}
    current = "header"
    lines = text.split("\n")
    for i, part in enumerate(lines):
        line = part + ("\n" if i < len(lines) - 1 else "")
        for name, prefix in SECTION_HEADERS:
            if rank[name] > rank[current] and line.startswith(prefix):
                current = name
                out.setdefault(name, [])
                break
        out[current].append(line)
    return {name: "".join(out[name]) for name in SECTIONS if name in out}


def blueprint_slot(header: str) -> Optional[str]:
    """The blueprint the header carries: the text after ``Blueprint: `` up to
    the newline before the ``Surface:`` line, or None when the header has none."""
    start = header.find("\n" + BLUEPRINT_LINE)
    if start < 0:
        return None
    start += 1 + len(BLUEPRINT_LINE)
    end = header.find("\n" + SURFACE_LINE, start)
    return header[start:end] if end >= 0 else None


def measure(text: str, stamp: Optional[str], transcript: str) -> dict:
    """One whole banner's row."""
    parts = split_sections(text)
    health = parts.get("health", "")
    slot = blueprint_slot(parts["header"])
    head = HEAD_RE.search(parts["header"])
    got = YIELD_RE.search(health)
    ledger = LEDGER_RE.search(health)
    goal = GOAL_RE.search(ledger.group(0)) if ledger else None
    room = HEADROOM_RE.search(ledger.group(0)) if ledger else None
    binds = BINDS_RE.search(health)
    before_tail = "".join(t for name, t in parts.items() if name != "orientation")
    return {
        "at": stamp, "transcript": transcript, "head": head.group(1) if head else None,
        "units": units(text), "sections": {name: units(t) for name, t in parts.items()},
        "blueprint": units(slot) if slot is not None else None,
        "head_only": bool(slot) and BLUEPRINT_HEAD_MARKER in slot,
        "yield": {"handed": int(got.group(1)), "kept": int(got.group(2)), "share": int(got.group(3))} if got else None,
        "goal_bytes": int(goal.group(1)) if goal else None,
        "goal_soft": int(goal.group(2)) if goal and goal.group(2) else None,
        "headroom": int(room.group(1)) if room else None,
        "loss": int(binds.group(1)) if binds else None,
        "clipped": before_tail.rstrip("\n").endswith(BODY_CUT_MARKER),
    }


def read_project(project: Path) -> dict:
    """Every hook context string under ``project``'s transcripts:
    {directory, transcripts, strings: [(stamp, transcript, hook, text)], unparsed, unreadable}."""
    files = sorted(p for p in project.glob("*.jsonl") if p.is_file())
    strings: list = []
    unparsed = 0
    unreadable: list = []
    for path in files:
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if HOOK_CONTEXT not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        unparsed += 1
                        continue
                    att = rec.get("attachment") if isinstance(rec, dict) else None
                    if not isinstance(att, dict) or att.get("type") != HOOK_CONTEXT:
                        continue
                    content = att.get("content")
                    for text in content if isinstance(content, list) else [content]:
                        if isinstance(text, str):
                            strings.append((rec.get("timestamp"), path.stem, att.get("hookName"), text))
        except OSError as exc:
            unreadable.append(f"{path.name}: {exc}")
    return {"directory": str(project), "transcripts": len(files), "strings": strings,
            "unparsed": unparsed, "unreadable": unreadable}


def git_is_ancestor(repo: Path) -> Callable[[str], Optional[bool]]:
    """Whether DEF-674's merge is in a HEAD's history, read in ``repo``: True,
    False, or None where git cannot say (the HEAD or the merge not in the clone)."""
    cache: dict = {}

    def check(head: str) -> Optional[bool]:
        if head not in cache:
            try:
                rc: Optional[int] = subprocess.run(  # spawn: ok no pipe: the return code alone is read
                    ["git", "-C", str(repo), "merge-base", "--is-ancestor", CEILING_MERGE, head],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT, check=False).returncode
            except (OSError, subprocess.SubprocessError):
                rc = None
            cache[head] = True if rc == 0 else False if rc == 1 else None
        return cache[head]
    return check


def spread(values: list) -> dict:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0}
    med = statistics.median(vals)
    return {"n": len(vals), "min": min(vals), "median": int(med) if med == int(med) else med, "max": max(vals)}


def census(src: dict, *, last: Optional[int] = None,
           is_ancestor: Optional[Callable[[str], Optional[bool]]] = None) -> dict:
    """The figures over ``src`` (``read_project``'s shape); ``last`` keeps the
    newest whole banners, ``is_ancestor`` reads a HEAD against the merge."""
    kinds = Counter({k: 0 for k in KINDS})
    newest: dict = {}
    rows = []
    for stamp, transcript, hook, text in src["strings"]:
        kind = kind_of(text, hook)
        kinds[kind] += 1
        if kind in ("spill", "compact", "compact_spill") and (stamp or "") > (newest.get(kind) or ""):
            newest[kind] = stamp
        if kind == "whole":
            rows.append(measure(text, stamp, transcript))
    rows.sort(key=lambda r: (parse_stamp(r["at"]) or datetime.min.replace(tzinfo=timezone.utc), r["transcript"]))
    every = len(rows)
    if last is not None:
        rows = rows[-last:]
    ceiling = parse_stamp(CEILING_AT)
    for r in rows:
        at = parse_stamp(r["at"])
        r["since_by_date"] = None if at is None else at >= ceiling
        r["since_by_head"] = is_ancestor(r["head"]) if (r["head"] and is_ancestor) else None
    yields = [r for r in rows if r["yield"]]
    since = [r for r in rows if r["since_by_date"]]
    named = [r for r in rows if r["head"]]
    for r in rows:
        y = r["yield"]
        r["bp_loss"] = y["handed"] - y["kept"] if y else None
        r["goal_excess"] = (max(0, r["goal_bytes"] - r["goal_soft"])
                            if r["goal_bytes"] is not None and r["goal_soft"] is not None else None)
        r["covers"] = (r["goal_excess"] + r["headroom"] >= r["bp_loss"]
                       if None not in (r["bp_loss"], r["goal_excess"], r["headroom"]) else None)
    return {
        "directory": src["directory"], "transcripts": src["transcripts"], "strings": len(src["strings"]),
        "unparsed_lines": src["unparsed"], "unreadable": src["unreadable"],
        "population": dict(kinds), "newest": newest,
        "window": {"kept": len(rows), "of": every, "first": rows[0]["at"] if rows else None,
                   "last": rows[-1]["at"] if rows else None},
        "ceiling": {
            "merge": CEILING_MERGE, "at": CEILING_AT,
            "by_date": {"before": sum(r["since_by_date"] is False for r in rows), "since": len(since),
                        "undated": sum(r["since_by_date"] is None for r in rows)},
            "by_head": {"named": len(named), "since": sum(r["since_by_head"] is True for r in named),
                        "before": sum(r["since_by_head"] is False for r in named),
                        "unknown": sum(r["since_by_head"] is None for r in named)},
        },
        "units": spread([r["units"] for r in rows]),
        "over_ceiling": [{k: r[k] for k in ("at", "units", "head", "since_by_date", "since_by_head")}
                         for r in rows if r["units"] > MAX_CONTEXT_CHARS],
        "sections": {name: spread([r["sections"].get(name) for r in rows]) for name in SECTIONS},
        "blueprint": spread([r["blueprint"] for r in rows]),
        "yields": {"n": len(yields), "since": sum(bool(r["yield"]) for r in since), "since_of": len(since),
                   "handed": spread([r["yield"]["handed"] for r in yields]),
                   "kept": spread([r["yield"]["kept"] for r in yields]),
                   "loss": spread([r["bp_loss"] for r in yields]),
                   "head_only": sum(r["head_only"] for r in rows),
                   "slot_matches": sum(r["blueprint"] == r["yield"]["kept"] for r in yields)},
        "clips": {"n": sum(r["clipped"] for r in rows), "binds_lines": sum(r["loss"] is not None for r in rows),
                  "loss": spread([r["loss"] for r in rows])},
        "goal": {"bytes": spread([r["goal_bytes"] for r in rows]),
                 "soft": sorted({r["goal_soft"] for r in rows if r["goal_soft"] is not None}),
                 "past_soft": sum(bool(r["goal_excess"]) for r in rows),
                 "headroom": spread([r["headroom"] for r in rows])},
        "starts": rows,
    }


def _ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _sp(s: dict) -> str:
    if not s.get("n"):
        return "n 0"
    return f"n {s['n']}, min/median/max {s['min']}/{s['median']}/{s['max']}"


def _side(flag: Optional[bool]) -> str:
    return "since" if flag is True else "before" if flag is False else "unknown"


def render(data: dict) -> list:
    """The summary lines."""
    p, c, w = data["population"], data["ceiling"], data["window"]
    newest = data["newest"]
    lines = [f"banner census: {data['transcripts']} transcripts, {data['strings']} hook context strings "
             f"({p['not_banner']} not a banner), directory {_ascii(data['directory'])}"]
    lines.append(f"population: whole {p['whole']}, spill {p['spill']}"
                 + (f" (newest {short_stamp(newest['spill'])})" if newest.get("spill") else "")
                 + f", compact {p['compact']}, compact spill {p['compact_spill']}, short {p['short']}, "
                 f"unclassified {p['unclassified']}")
    if data["unparsed_lines"]:
        lines.append(f"note: {data['unparsed_lines']} line(s) naming hook context do not parse; not counted")
    for item in data["unreadable"]:
        lines.append(f"note: unreadable transcript {_ascii(item)}")
    if not w["kept"]:
        lines.append("note: no whole banner in this directory")
        return lines
    scope = "all" if w["kept"] == w["of"] else f"the newest {w['kept']} of"
    lines.append(f"window: {scope} {w['of']} whole banners, {short_stamp(w['first'])} .. {short_stamp(w['last'])}")
    d, h = c["by_date"], c["by_head"]
    lines.append(f"ceiling: DEF-674's merge {c['merge'][:8]} at {c['at']}; by date: before {d['before']}, "
                 f"since {d['since']}" + (f", undated {d['undated']}" if d["undated"] else "")
                 + f"; by HEAD ({h['named']} of {w['kept']} name one): since {h['since']}, before {h['before']}, "
                 f"not in this clone {h['unknown']}")
    lines.append(f"total units: {_sp(data['units'])} (ceiling {MAX_CONTEXT_CHARS}, host cap {HOST_CONTEXT_CAP_CHARS})")
    over = data["over_ceiling"]
    lines.append(f"over the ceiling: {len(over)}" + (": " + "; ".join(
        f"{short_stamp(o['at'])} {o['units']} HEAD {o['head'] or '-'} ({_side(o['since_by_date'])} by date"
        + (f", {_side(o['since_by_head'])} by HEAD" if o["head"] else "") + ")" for o in over) if over else ""))
    for name in SECTIONS:
        lines.append(f"section {name}: {_sp(data['sections'][name])}")
    lines.append(f"blueprint slot: {_sp(data['blueprint'])}")
    y = data["yields"]
    lines.append(f"yields: {y['n']} of {w['kept']} (since the ceiling by date {y['since']} of {y['since_of']}); "
                 f"handed in {_sp(y['handed'])}; kept {_sp(y['kept'])}; loss {_sp(y['loss'])}; cut to its header "
                 f"line {y['head_only']}; the slot equals the yield line's kept figure on {y['slot_matches']} of {y['n']}")
    k = data["clips"]
    lines.append(f"clips: {k['n']} (the body-cut marker), the binds line on {k['binds_lines']}, body loss {_sp(k['loss'])}")
    g = data["goal"]
    soft = "/".join(str(s) for s in g["soft"]) or "-"
    lines.append(f"goal bytes (the health ledger): {_sp(g['bytes'])}; soft budget {soft}, past it on "
                 f"{g['past_soft']}; headroom {_sp(g['headroom'])}")
    return lines


def ranking(data: dict) -> list:
    """The per-start table: one row per whole banner kept."""
    def cell(v: object) -> str:
        return "-" if v is None else ("yes" if v is True else "no" if v is False else str(v))
    out = [f"{'at':<20}  {'head':<8}  {'units':>5}  {'bp kept/handed':>14}  {'goal':>5}  {'headroom':>8}  "
           f"{'clip':<4}  {'loss':>5}  {'excess':>6}  covers"]
    for r in data["starts"]:
        y = r["yield"]
        bp = f"{y['kept']}/{y['handed']}" if y else (f"{r['blueprint']} whole" if r["blueprint"] is not None else "-")
        out.append(f"{short_stamp(r['at']):<20}  {(r['head'] or '-')[:8]:<8}  {r['units']:>5}  {bp:>14}  "
                   f"{cell(r['goal_bytes']):>5}  {cell(r['headroom']):>8}  {cell(r['clipped']):<4}  "
                   f"{cell(r['bp_loss']):>5}  {cell(r['goal_excess']):>6}  {cell(r['covers'])}")
    return out


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--project", required=True,
                    help="one Claude Code project directory (~/.claude/projects/<dir>); its *.jsonl are read")
    ap.add_argument("--repo", default=str(ROOT),
                    help="the clone a banner's HEAD is read against DEF-674's merge in (default: this one)")
    ap.add_argument("--last", type=int, metavar="N", help="keep the newest N whole banners")
    ap.add_argument("--ranking", action="store_true", help="print the per-start table after the summary")
    ap.add_argument("--json", action="store_true", help="the same figures as JSON")
    args = ap.parse_args(argv)
    if args.last is not None and args.last < 1:
        print("banner_census: --last N keeps the newest N whole banners; N is 1 or more", file=sys.stderr)
        return 2
    project = Path(args.project).expanduser()
    if not project.is_dir():
        print(f"banner_census: --project is not a directory: {_ascii(str(project))}", file=sys.stderr)
        return 2
    try:
        src = read_project(project)
    except OSError as exc:
        print(f"banner_census: cannot read {_ascii(str(project))}: {_ascii(str(exc))}", file=sys.stderr)
        return 2
    data = census(src, last=args.last, is_ancestor=git_is_ancestor(Path(args.repo)))
    if args.json:
        if not args.ranking:
            data = {k: v for k, v in data.items() if k != "starts"}
        print(json.dumps(data, indent=2))
    else:
        lines = render(data)
        if args.ranking and data["starts"]:
            lines += ["", *ranking(data)]
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
