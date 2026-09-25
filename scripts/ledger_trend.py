#!/usr/bin/env python3
"""Read the forward ledger's history off the record branch: rows closed vs filed.

Why this exists
---------------
Contract rule 5 of ``task-packs/FORWARD_LEDGER.md`` says the live count can
never be the "ready" signal: every landed pack emits deferrals, so the backlog
is a divergent series and the count measures residual, not flow. The two
instruments it names instead -- adopter-facing defects fixed vs introduced,
and the blocker yield of the logic-bug population -- were hand-classified
once (2026-08-05) and never recomputed. Two things make them derivable now:
``scripts/record_snapshot.py`` has carried a copy of the ledger on the orphan
``record`` ref at every handoff since 2026-08-31, and every member row carries
a stable id, a strike marker and (since 2026-09-08) a population and an
audience. Diffing the id sets of consecutive snapshots is the flow.

What it measures
----------------
Per snapshot (against the one before it) and for the whole window:

* ``filed``   -- ids the previous snapshot did not carry
* ``struck``  -- ids struck now that were live before
* ``churn``   -- ids filed AND struck inside the window (found in a lane and
  fixed in it; counted in both of the above, named apart so a "60 closed"
  headline cannot pass off in-lane churn as backlog drained)
* ``net``     -- live rows now minus live rows then
* ``dropped`` / ``reopened`` -- a live row that vanished without a strike
  (a rebuild), a struck row live again; both move ``net`` without being
  filed or struck, so they are named and the window identity is checked:
  ``net == replacement - backlog_struck - dropped + reopened``
* the same split by audience and by population, using each id's tags as the
  LATEST snapshot records them (a struck row keeps its cells), then the last
  snapshot that carried the id, then ``UNTAGGED`` -- never a guess. The
  record ref is written at handoff, so tags landed since the last snapshot
  are invisible here: the header names the snapshot the tags come from.

The per-step ``struck`` column never sees a row filed and struck inside one
step (it was never live in a snapshot), so its sum is not the window's
closures; the report prints the reconciliation rather than leaving a reader
to add the column.

The parsers are ``generate_ledger_regions.py``'s: the ledger's grammar has one
home, and the 08-31 -> 09-08 window this was first run on found the file's
own headline off by 34 for eight days because nothing diffed it.

Usage::

    python3 scripts/ledger_trend.py                  # every snapshot, oldest first, then the window
    python3 scripts/ledger_trend.py --since 2026-09-02    # by date
    python3 scripts/ledger_trend.py --from faf9121         # from one snapshot: after a sweep day
    python3 scripts/ledger_trend.py --json
    python3 scripts/ledger_trend.py --ref record --path task-packs/FORWARD_LEDGER.md

Exit codes: 0 = report printed, or a note when the ref is absent or carries
fewer than two snapshots (self-host only: an adopter tree has neither); 2 =
usage error.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[1]
_DEFAULT_REF = "record"
_DEFAULT_PATH = "task-packs/FORWARD_LEDGER.md"
UNTAGGED = "UNTAGGED"


def _gen():
    """The ledger's grammar, loaded once per process. Reusing an already-loaded
    copy matters: ``ledger_row.py`` and the test module bind the same name, and
    a second exec would swap the object under them."""
    loaded = sys.modules.get("generate_ledger_regions")
    if loaded is not None and hasattr(loaded, "ledger_sections"):
        return loaded
    spec = importlib.util.spec_from_file_location(
        "generate_ledger_regions", _HERE.parent / "generate_ledger_regions.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


def snapshots(repo: Path, ref: str, path: str, since: str | None = None,
              start: str | None = None) -> list[tuple[str, str]]:
    """``[(hash, date)]`` of every commit on ``ref`` that touched ``path``, oldest
    first. ``since`` keeps snapshots dated on or after a day; ``start`` keeps
    the named snapshot (a hash prefix) and everything after it -- a day can hold
    a census that files forty rows at once, and the working rate is measured
    from the snapshot after it, not from that morning."""
    run = _git(repo, "log", "--format=%H %ad", "--date=short", ref, "--", path)
    if run.returncode != 0:
        return []
    out = [tuple(ln.split()) for ln in run.stdout.splitlines() if ln.strip()]
    out.reverse()
    if since:
        out = [s for s in out if s[1] >= since]
    if start:
        idx = next((k for k, s in enumerate(out) if s[0].startswith(start)), None)
        out = out[idx:] if idx is not None else []
    return out


def ledger_at(repo: Path, commit: str, path: str) -> str | None:
    run = _git(repo, "show", f"{commit}:{path}")
    return run.stdout if run.returncode == 0 else None


def state(gen, text: str) -> dict[str, dict[str, object]]:
    """``{id: {"struck": bool, "population": tok, "audience": tok}}`` for every member row."""
    tags = gen.declared_class_tags(text)
    out: dict[str, dict[str, object]] = {}
    for name, rows in gen.ledger_sections(text).items():
        cpop, caud = tags.get(name, (None, None))
        for row in rows:
            m = gen._MEMBER_ID.match(row)
            if not m:
                continue
            cells = gen.member_cells(row)
            out[m.group(2)] = {
                "struck": gen._is_struck(row),
                "population": _tag(gen, cpop, cells, 4, gen.POPULATIONS),
                "audience": _tag(gen, caud, cells, 5, gen.AUDIENCES),
            }
    return out


def _tag(gen, class_tag: str | None, cells: list[str], idx: int, vocab: tuple[str, ...]) -> str:
    """A row's tag on one axis: the class's when the class declares one, the
    row's own cell when the class is MIXED (read by lead token, as the
    generator reads a class cell -- a struck row's bolded cell must not read
    as untagged), else UNTAGGED."""
    if class_tag in vocab:
        return class_tag
    if class_tag == gen.MIXED and len(cells) > idx:
        m = gen._LEAD_TOKEN.match(cells[idx])
        if m and m.group(1) in vocab:
            return m.group(1)
    return UNTAGGED


def _split(ids: set[str], tags: dict[str, dict[str, object]], axis: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for i in sorted(ids):
        tok = str(tags.get(i, {}).get(axis, UNTAGGED))
        counts[tok] = counts.get(tok, 0) + 1
    return dict(sorted(counts.items()))


def diff(prev: dict[str, dict[str, object]], cur: dict[str, dict[str, object]],
         tags: dict[str, dict[str, object]]) -> dict[str, object]:
    """One step: what ``cur`` filed, struck, dropped and reopened relative to ``prev``."""
    live_prev = {i for i, s in prev.items() if not s["struck"]}
    live_cur = {i for i, s in cur.items() if not s["struck"]}
    filed = set(cur) - set(prev)
    struck = {i for i in cur if cur[i]["struck"] and i in live_prev}
    dropped = live_prev - set(cur)
    reopened = {i for i in live_cur if i in prev and prev[i]["struck"]}
    return {
        "live": len(live_cur),
        "filed": sorted(filed),
        "struck": sorted(struck),
        "dropped": sorted(dropped),
        "reopened": sorted(reopened),
        "net": len(live_cur) - len(live_prev),
        "filed_by_audience": _split(filed, tags, "audience"),
        "struck_by_audience": _split(struck, tags, "audience"),
        "filed_by_population": _split(filed, tags, "population"),
        "struck_by_population": _split(struck, tags, "population"),
    }


_RATIO_FLOOR = 5


def window(first: dict[str, dict[str, object]], last: dict[str, dict[str, object]],
           tags: dict[str, dict[str, object]], ever_live: set[str]) -> dict[str, object]:
    """The whole span: backlog drained vs replaced vs churned, with the two
    transitions that move ``net`` without a filing or a strike named, and the
    identity between them checked."""
    live_first = {i for i, s in first.items() if not s["struck"]}
    live_last = {i for i, s in last.items() if not s["struck"]}
    filed = set(last) - set(first)
    backlog_struck = {i for i in live_first if i in last and last[i]["struck"]}
    dropped = live_first - set(last)
    reopened = {i for i in live_last if i in first and first[i]["struck"]}
    churn = {i for i in filed if last[i]["struck"]}
    replacement = filed - churn
    same_step_churn = {i for i in churn if i not in ever_live}
    drained = len(backlog_struck)
    ratio = (len(replacement) / drained) if drained >= _RATIO_FLOOR else None
    net = len(live_last) - len(live_first)
    gap = net - (len(replacement) - drained - len(dropped) + len(reopened))
    return {
        "live_first": len(live_first),
        "live_last": len(live_last),
        "net": net,
        "backlog_struck": sorted(backlog_struck),
        "filed": sorted(filed),
        "churn": sorted(churn),
        "same_step_churn": sorted(same_step_churn),
        "replacement": sorted(replacement),
        "dropped": sorted(dropped),
        "reopened": sorted(reopened),
        "identity_gap": gap,
        "replacement_per_drained": ratio,
        "denominator": drained,
        "backlog_struck_by_audience": _split(backlog_struck, tags, "audience"),
        "replacement_by_audience": _split(replacement, tags, "audience"),
        "churn_by_audience": _split(churn, tags, "audience"),
        "backlog_struck_by_population": _split(backlog_struck, tags, "population"),
        "replacement_by_population": _split(replacement, tags, "population"),
        "churn_by_population": _split(churn, tags, "population"),
    }


def trend(repo: Path, ref: str, path: str, since: str | None,
          start: str | None = None) -> dict[str, object] | None:
    """The full report, or None when there is nothing to diff."""
    gen = _gen()
    snaps = snapshots(repo, ref, path, since, start)
    states: list[tuple[str, str, dict[str, dict[str, object]]]] = []
    skipped: list[str] = []
    for commit, day in snaps:
        text = ledger_at(repo, commit, path)
        if text is None:
            skipped.append(f"{day} {commit[:7]}")
            continue
        states.append((commit[:7], day, state(gen, text)))
    if len(states) < 2:
        return None
    # Tags as the latest snapshot records them; an id absent there keeps the
    # tags of the last snapshot that carried it. Oldest first, so later wins.
    tags: dict[str, dict[str, object]] = {}
    ever_live: set[str] = set()
    for _c, _d, st in states:
        for i, s in st.items():
            tags[i] = s
            if not s["struck"]:
                ever_live.add(i)
    steps = []
    for (_pc, _pd, prev), (cc, cd, cur) in zip(states, states[1:]):
        steps.append({"commit": cc, "date": cd, **diff(prev, cur, tags)})
    return {
        "ref": ref,
        "path": path,
        "first": {"commit": states[0][0], "date": states[0][1]},
        "last": {"commit": states[-1][0], "date": states[-1][1]},
        "skipped_snapshots": skipped,
        "steps": steps,
        "window": window(states[0][2], states[-1][2], tags, ever_live),
    }


def _fmt_split(d: dict[str, int]) -> str:
    return " ".join(f"{k}={v}" for k, v in d.items()) or "-"


def render(report: dict[str, object], today: date | None = None) -> str:
    last = report["last"]
    age = (today or date.today()) - date.fromisoformat(last["date"])
    lines = [
        f"ledger trend on {report['ref']} ({report['first']['date']} {report['first']['commit']} "
        f"-> {last['date']} {last['commit']}; last snapshot {age.days} day(s) old)",
        f"tags as of snapshot {last['commit']} -- the working ledger is not read; UNTAGGED = "
        "tagged after that snapshot, or genuinely untagged",
    ]
    if report["skipped_snapshots"]:
        lines.append(f"skipped {len(report['skipped_snapshots'])} snapshot(s) without the ledger: "
                     + ", ".join(report["skipped_snapshots"]))
    lines.append(f"{'date':10} {'commit':7} {'live':>4} {'filed':>5} {'struck':>6} {'net':>4}  "
                 "struck by audience / filed by audience")
    for s in report["steps"]:
        extra = ""
        if s["dropped"] or s["reopened"]:
            extra = f"  dropped={len(s['dropped'])} reopened={len(s['reopened'])}"
        lines.append(f"{s['date']:10} {s['commit']:7} {s['live']:4} {len(s['filed']):5} "
                     f"{len(s['struck']):6} {s['net']:+4}  {_fmt_split(s['struck_by_audience'])} / "
                     f"{_fmt_split(s['filed_by_audience'])}{extra}")
    w = report["window"]
    column = sum(len(s["struck"]) for s in report["steps"])
    lines += [
        "",
        f"window: live {w['live_first']} -> {w['live_last']} (net {w['net']:+})",
        f"  backlog struck (live at the start, struck by the end): {len(w['backlog_struck'])}  "
        f"by audience {_fmt_split(w['backlog_struck_by_audience'])}  by population "
        f"{_fmt_split(w['backlog_struck_by_population'])}",
        f"  filed: {len(w['filed'])} = churn {len(w['churn'])} (filed and struck inside the window) "
        f"+ replacement {len(w['replacement'])} (filed, still open)",
        f"  replacement by audience {_fmt_split(w['replacement_by_audience'])}  by population "
        f"{_fmt_split(w['replacement_by_population'])}",
        f"  churn by audience {_fmt_split(w['churn_by_audience'])}  by population "
        f"{_fmt_split(w['churn_by_population'])}",
        f"  the steps' struck column sums to {column} = backlog {len(w['backlog_struck'])} + churn "
        f"struck in a later step {len(w['churn']) - len(w['same_step_churn'])}; "
        f"{len(w['same_step_churn'])} churn row(s) were filed and struck inside one step and "
        "appear in no step's column",
    ]
    if w["dropped"] or w["reopened"]:
        lines.append(f"  dropped without a strike: {len(w['dropped'])} {w['dropped']}; reopened: "
                     f"{len(w['reopened'])} {w['reopened']}")
    if w["identity_gap"]:
        lines.append(f"  WARN: net {w['net']:+} != replacement - backlog - dropped + reopened "
                     f"(gap {w['identity_gap']:+}); the diff missed a transition")
    if w["replacement_per_drained"] is None:
        lines.append(f"  replacement per backlog row drained: n too small ({w['denominator']} "
                     f"drained, floor {_RATIO_FLOOR})")
    else:
        lines.append(f"  replacement per backlog row drained: {w['replacement_per_drained']:.2f} "
                     f"over {w['denominator']} drained  (contract rule 5: below 1.0 is convergent; "
                     "a count alone cannot say)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=str(_ROOT), help="the git checkout to read (default: this one)")
    ap.add_argument("--ref", default=_DEFAULT_REF, help="the ref carrying the snapshots (default: record)")
    ap.add_argument("--path", default=_DEFAULT_PATH, help="the ledger's path inside the ref")
    ap.add_argument("--since", help="first snapshot date to include, YYYY-MM-DD")
    ap.add_argument("--from", dest="start", metavar="COMMIT",
                    help="first snapshot to include, by hash prefix (start after a sweep day)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    if args.since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.since):
        print(f"ledger_trend: --since takes YYYY-MM-DD, not {args.since!r}", file=sys.stderr)
        return 2
    if args.start and not snapshots(repo, args.ref, args.path, args.since, args.start):
        # A typo'd hash must not read as "no record ref": that message says the
        # instrument does not apply here, and the caller would believe it.
        print(f"ledger_trend: no snapshot of {args.path} on {args.ref!r} matches --from "
              f"{args.start!r}" + (f" on or after --since {args.since}" if args.since else "")
              + " (git log --format=%h --date=short " + args.ref + " -- " + args.path
              + " lists them)", file=sys.stderr)
        return 2
    report = trend(repo, args.ref, args.path, args.since, args.start)
    if report is None:
        print(f"ledger_trend: fewer than two snapshots of {args.path} on {args.ref!r} in {repo} "
              "-- nothing to diff (the record ref is written at handoff by "
              "scripts/record_snapshot.py; an adopter tree has none)")
        return 0
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
