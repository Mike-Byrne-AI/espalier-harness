#!/usr/bin/env python3
"""Read the forward ledger's history off its snapshots: rows closed vs filed.

Which ref
---------
Without ``--ref``, the base branch's remote-tracking ref (``origin/<base>``,
read from the local ``origin/HEAD``) when the ledger is tracked there -- every
merge that touched it is a snapshot -- else the ``record`` ref
(:func:`default_ref`). The fixed ``record`` default went stale once the ledger
was tracked on main: on 2026-10-14 it printed its last step for 2026-09-21.

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
  snapshot that carried the id, then ``UNTAGGED`` -- never a guess. Tags
  landed since the last snapshot on the ref read (a merge on the base branch,
  a handoff on ``record``) are invisible here: the header names the snapshot
  the tags come from.

The per-step ``struck`` column never sees a row filed and struck inside one
step (it was never live in a snapshot), so its sum is not the window's
closures; the report prints the reconciliation and checks it: every strike in
the column stands at the last snapshot (backlog, later-struck churn, or a row
struck at the start, reopened and struck again), was undone by a later reopen,
or belongs to a row pruned from the file after it, and a strike that fits none
of those is a ``WARN`` (``struck_column.gap`` in the JSON). The snapshots are
the ref's first-parent line, so a merge-heavy ref (``main``) is read as one
line of history and a lane's own commits never interleave with the merges
that landed them; a linear ref (``record``, 104 commits on both walks on
2026-10-11) reads the same either way, and the header counts the commits off
the first-parent line, so a ref that starts merging says so.

The parsers are ``generate_ledger_regions.py``'s: the ledger's grammar has one
home, and the 08-31 -> 09-08 window this was first run on found the file's
own headline off by 34 for eight days because nothing diffed it.

Usage::

    python3 scripts/ledger_trend.py                  # every snapshot, oldest first, then the window
    python3 scripts/ledger_trend.py --since 2026-09-02    # by date
    python3 scripts/ledger_trend.py --ref record --from faf9121   # from one snapshot: after a sweep day
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
from pathlib import Path, PurePosixPath

_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[1]
_DEFAULT_REF = "record"
_DEFAULT_PATH = "task-packs/FORWARD_LEDGER.md"


def _merge_rules():
    """``tools/cc/_merge_rules.py`` by path: ``base_branch`` is the one read of
    the remote's default branch (the board and ``ship.py`` read it too)."""
    spec = importlib.util.spec_from_file_location("_lt_merge_rules", _ROOT / "tools" / "cc" / "_merge_rules.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def default_ref(repo: Path, path: str) -> str:
    """The ref the snapshots are read from when ``--ref`` is not given: the
    base branch's remote-tracking ref (``origin/<base>``, the base read from
    the local ``origin/HEAD``) when the ledger is tracked there, else the
    ``record`` ref -- an adopter's, or a tree whose ledger is gitignored and
    snapshotted at handoff. Measured 2026-10-14 on the dispatcher's clone: the
    old default (``record``) printed its last step for 2026-09-21 while main
    carried the ledger to the day; probable, not measured, cause: ``record``
    stopped carrying the ledger once main tracked it. Read with
    ``--ref origin/main`` on 2026-10-15, the same script printed steps
    through that day, strikes 8 / 3 / 6 on 10-12 to 10-14."""
    base = f"origin/{_merge_rules().base_branch(repo)}"
    # the ledger as one file, or as its rows under the row-file directory: a
    # base that keeps only the rows still carries the ledger
    for where in (path, _row_dir(path)):
        if _git(repo, "cat-file", "-e", f"{base}:{where}").returncode == 0:
            return base
    return _DEFAULT_REF
UNTAGGED = "UNTAGGED"


def _gen():
    """The ledger's grammar, loaded once per process. Reusing an already-loaded
    copy matters: ``ledger_row.py`` and the test module bind the same name, and
    a second exec would swap the object under them."""
    loaded = sys.modules.get("generate_ledger_regions")
    if loaded is not None and hasattr(loaded, "ledger_sections"):
        return loaded
    spec = importlib.util.spec_from_file_location(
        "generate_ledger_regions", _ROOT / "tools" / "cc" / "generate_ledger_regions.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


def _row_dir(path: str) -> str:
    """The row-file directory beside the ledger at ``path`` (where a
    repository keeps its rows as files), as the loader names it."""
    return _gen().record_fragments().ledger_fragment_dir(PurePosixPath(path)).as_posix()


def _log(repo: Path, ref: str, path: str, first_parent: bool) -> list[tuple[str, str]]:
    """``[(hash, date)]`` of the commits on ``ref`` that touched ``path`` or the
    row-file directory beside it, oldest first: the ref's first-parent line, or
    every commit in the order the plain log gives them. A commit that only
    filed or struck a row file changed the ledger as its readers see it."""
    args = ["log"] + (["--first-parent"] if first_parent else []) + [
        "--format=%H %ad", "--date=short", ref, "--", path, _row_dir(path)]
    run = _git(repo, *args)
    if run.returncode != 0:
        return []
    out = [tuple(ln.split()) for ln in run.stdout.splitlines() if ln.strip()]
    out.reverse()
    return out  # type: ignore[return-value]


def off_first_parent(repo: Path, ref: str, path: str, since: str | None = None) -> int:
    """How many commits touching ``path`` on ``ref`` (dated on or after
    ``since``) sit off its first-parent line: a lane's own commits, which the
    walk reads through the merges that landed them. Zero on a linear ref, and
    the header prints it, so a ``record`` ref that starts merging (two machines
    writing it) says so instead of losing snapshots silently."""
    on = {h for h, d in _log(repo, ref, path, True) if not since or d >= since}
    every = {h for h, d in _log(repo, ref, path, False) if not since or d >= since}
    return len(every - on)


def snapshots(repo: Path, ref: str, path: str, since: str | None = None,
              start: str | None = None) -> list[tuple[str, str]]:
    """``[(hash, date)]`` of every commit on ``ref``'s first-parent line that
    touched ``path``, oldest first. The walk follows first parents because on a
    merge-heavy ref (``main``, where every lane lands as a merge) the plain log
    orders the lanes' own commits among the merges by date, so consecutive
    snapshots alternate between parallel lanes and one strike reads as a
    reopen and a second strike (the column summed to 365 against 85 + 40 on
    2026-10-11); on a linear ref (``record``, 104 commits either way that day)
    the two walks are the same list. ``since`` keeps snapshots dated on or after
    a day; ``start`` keeps the named snapshot (a hash prefix) and everything
    after it -- a day can hold a census that files forty rows at once, and the
    working rate is measured from the snapshot after it, not from that
    morning."""
    out = _log(repo, ref, path, first_parent=True)
    if since:
        out = [s for s in out if s[1] >= since]
    if start:
        idx = next((k for k, s in enumerate(out) if s[0].startswith(start)), None)
        out = out[idx:] if idx is not None else []
    return out


def _row_files_at(repo: Path, commit: str, directory: str) -> list[tuple[str, str]]:
    """``(name, text)`` of every file directly under ``directory`` at
    ``commit``: one ``ls-tree`` and one ``cat-file --batch`` (measured
    2026-10-13: 83 snapshots of 781 files in about 10 s)."""
    ls = _git(repo, "ls-tree", commit, "--", directory + "/")
    entries = [ln.split("\t", 1) for ln in ls.stdout.splitlines() if "\t" in ln] if ls.returncode == 0 else []
    blobs = [(meta.split()[2], name.rsplit("/", 1)[-1]) for meta, name in entries if meta.split()[1] == "blob"]
    if not blobs:
        return []
    run = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"], capture_output=True, check=False,
                         input="".join(sha + "\n" for sha, _name in blobs).encode("ascii"))
    out, at, files = run.stdout, 0, []
    for _sha, name in blobs:
        nl = out.index(b"\n", at)
        size = int(out[at:nl].split()[2])
        files.append((name, out[nl + 1:nl + 1 + size].decode("utf-8", errors="replace")))
        at = nl + 1 + size + 1
    return files


def ledger_at(repo: Path, commit: str, path: str) -> str | None:
    """The ledger as its readers saw it at ``commit``: the file with the row
    files beside it then placed in it (the loader's view, from texts)."""
    run = _git(repo, "show", f"{commit}:{path}")
    if run.returncode != 0:
        return None
    rows = _row_files_at(repo, commit, _row_dir(path))
    return _gen().record_fragments().ledger_text_from_texts(run.stdout, rows) if rows else run.stdout


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
    w = window(states[0][2], states[-1][2], tags, ever_live)
    return {
        "ref": ref,
        "path": path,
        "first": {"commit": states[0][0], "date": states[0][1]},
        "last": {"commit": states[-1][0], "date": states[-1][1]},
        "skipped_snapshots": skipped,
        "steps": steps,
        "window": w,
        "struck_column": struck_column(steps, states[-1][2], w),
        "off_first_parent": off_first_parent(repo, ref, path, since),
    }


def struck_column(steps: list[dict[str, object]], last: dict[str, dict[str, object]],
                  w: dict[str, object]) -> dict[str, object]:
    """Where every strike in the per-step column ends up, so the sum the report
    prints is checked rather than asserted. A strike either stands at the last
    snapshot (the window's backlog or its later-struck churn, or a row that was
    struck at the start, reopened and struck again), was undone by a later
    reopen, or belongs to a row pruned from the file after it. What is left is
    the gap: a strike the window cannot place (a struck row that vanished and
    came back live, which the diff can only read as a filing). A strike is
    pending until a reopen undoes it; only a pending strike stands at the end,
    is struck again, or leaves the file, so a row struck, reopened and then
    pruned is placed once (the reviews of 2026-10-11 found it placed twice)."""
    column = sum(len(s["struck"]) for s in steps)
    pending: set[str] = set()
    undone = 0
    for s in steps:
        for i in s["reopened"]:
            if i in pending:
                undone += 1
                pending.discard(i)
        pending.update(s["struck"])
    backlog = set(w["backlog_struck"])
    churn_later = set(w["churn"]) - set(w["same_step_churn"])
    stands = {i for i in pending if i in last and last[i]["struck"]}
    restruck = stands - backlog - churn_later
    dropped = {i for i in pending if i not in last}
    placed = len(backlog) + len(churn_later) + undone + len(restruck) + len(dropped)
    return {
        "sum": column,
        "backlog": len(backlog),
        "churn_later": len(churn_later),
        "undone": undone,
        "restruck": sorted(restruck),
        "dropped": sorted(dropped),
        "gap": column - placed,
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
        f"walk: {report['ref']}'s first-parent line; {report['off_first_parent']} commit(s) touching "
        "the ledger sit off it (a lane's own commits, read through the merges that landed them)",
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
    sc = report["struck_column"]
    placed = ""
    if sc["undone"]:
        placed += f" + struck then reopened {sc['undone']}"
    if sc["restruck"]:
        placed += f" + reopened then struck again {len(sc['restruck'])}"
    if sc["dropped"]:
        placed += f" + struck then dropped {len(sc['dropped'])}"
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
        f"  the steps' struck column sums to {sc['sum']} = backlog {sc['backlog']} + churn "
        f"struck in a later step {sc['churn_later']}{placed}; "
        f"{len(w['same_step_churn'])} churn row(s) were filed and struck inside one step and "
        "appear in no step's column",
    ]
    if sc["gap"]:
        lines.append(f"  WARN: the struck column does not reconcile (gap {sc['gap']:+}): a strike the "
                     "window cannot place; the diff missed a transition")
    if w["dropped"] or w["reopened"]:
        lines.append(f"  dropped (live at the start, absent at the end): {len(w['dropped'])} "
                     f"{w['dropped']}; reopened: {len(w['reopened'])} {w['reopened']}")
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
    ap.add_argument("--ref", default=None,
                    help="the ref carrying the snapshots (default: origin/<the base branch> when the ledger "
                         "is tracked there, else record)")
    ap.add_argument("--path", default=_DEFAULT_PATH, help="the ledger's path inside the ref")
    ap.add_argument("--since", help="first snapshot date to include, YYYY-MM-DD")
    ap.add_argument("--from", dest="start", metavar="COMMIT",
                    help="first snapshot to include, by hash prefix (start after a sweep day)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    if args.ref is None:
        args.ref = default_ref(repo, args.path)
        if args.ref == _DEFAULT_REF:
            base = f"origin/{_merge_rules().base_branch(repo)}"
            if _git(repo, "rev-parse", "--verify", "--quiet", base).returncode == 0:
                print(f"ledger_trend: {base} carries no ledger at {args.path}; reading {_DEFAULT_REF!r}",
                      file=sys.stderr)
    if args.since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.since):
        print(f"ledger_trend: --since takes YYYY-MM-DD, not {args.since!r}", file=sys.stderr)
        return 2
    if args.start and not snapshots(repo, args.ref, args.path, args.since, args.start):
        # A typo'd hash must not read as "no record ref": that message says the
        # instrument does not apply here, and the caller would believe it. And a
        # hash copied from the plain log can sit on a lane, off the line the
        # walk reads: say so, or the caller loops on the hint's own output.
        listing = ("git log --first-parent --format=%h --date=short " + args.ref + " -- "
                   + args.path + " lists the snapshots")
        on_line = {h for h, _d in _log(repo, args.ref, args.path, True)}
        off_line = {h for h, _d in _log(repo, args.ref, args.path, False)} - on_line
        if any(h.startswith(args.start) for h in off_line):
            print(f"ledger_trend: --from {args.start!r} names a commit off {args.ref!r}'s "
                  "first-parent line (a lane's own commit); the walk reads the merges that "
                  f"landed the lanes, so name the merge ({listing})", file=sys.stderr)
            return 2
        print(f"ledger_trend: no snapshot of {args.path} on {args.ref!r} matches --from "
              f"{args.start!r}" + (f" on or after --since {args.since}" if args.since else "")
              + f" ({listing})", file=sys.stderr)
        return 2
    report = trend(repo, args.ref, args.path, args.since, args.start)
    if report is None:
        print(f"ledger_trend: fewer than two snapshots of {args.path} on {args.ref!r}'s "
              f"first-parent line in {repo} -- nothing to diff"
              + (" (the record ref is written at handoff by scripts/record_snapshot.py; an "
                 "adopter tree has none)" if args.ref == _DEFAULT_REF else
                 " (a lane's own commits are read through the merges that landed them)"))
        return 0
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
