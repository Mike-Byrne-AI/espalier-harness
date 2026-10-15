#!/usr/bin/env python3
"""How long a worker's request waits for its answer: the dispatcher split's metric.

Why this exists
---------------
The seats' protocol (``memory/parallel-work-protocol.md``) has a worker ask the
dispatcher, never another worker, and the dispatcher split of 2026-10-12 19Z
pre-registered its metric: a worker request answered within the hour. The
figure was read once by hand over every mail ref, and nothing could read it
again. This is the instrument.

What it measures
----------------
Every message on every machine's mail ref -- fetched first (``--no-fetch``
reads what is here), the remote-tracking refs ``refs/remotes/origin/mail/*`` and
this clone's own ``refs/heads/mail/*`` (which may be ahead of origin's copy),
the same message read twice counted once by its id (the remote-tracking copy
first). The report says how fresh each ref is: the stamp of its newest message.

* A **worker request** is a ``request`` whose sender is not the dispatcher. For
  ``--split`` the dispatcher is the seat the split made one, ``air``
  (:data:`SPLIT_DISPATCHER`), so a later change of dispatcher never rewrites
  the pre-registered baseline; any other window reads ``dispatcher`` from
  ``espalier.toml`` and prints how it read it, refusing an unusable setting.
* Its **answer** is the first ``ack`` -- by its own stamp, at or after the
  request's, and before ``--until`` when one is given -- whose ``ack`` field
  names the request's full id, from any seat but the asker: the rule
  ``tools/cc/mail.py::live_requests`` folds by, so a note, a release or an
  assign naming the id answers nothing. An asker's own ack (a request it closed
  itself, moot or withdrawn) is no one's answer: it leaves the figures and is
  listed as closed by its asker.
* The **latency** is the answer's stamp minus the request's, in minutes. A
  message whose stamp does not parse is skipped and counted, never a crash.

Per window -- ``--since`` / ``--until`` (ISO stamps or dates, UTC; a request
belongs to the window its own stamp falls in, ``[since, until)``), or
``--split``, the dispatcher split's two windows (``--until`` ends the second) --
the count of answered requests, the median, the p75 and the max; the
pre-registered metric itself, how many were answered within the hour (an ask
unanswered past the hour at the window's end is a miss, not an absence); who
answered; and every request still unanswered with its age at the window's end
(``--until``, or now). Minutes print rounded to the whole minute, half to even
(Python's ``round``). The median is ``statistics.median`` (the middle pair's
mean at an even count); the **p75 is nearest-rank**: the value at rank
``ceil(0.75 * n)`` of the sorted latencies, a value that occurred.

The figures the dispatcher reported by hand on 2026-10-14 (n=21, median 268,
p75 722 before the split; n=19, median 6, p75 8, max 16 since) came from a run
at 2026-10-15T02:10:45Z over the same refs with the same pairing, a floor-rank
p75 (sorted index ``int(0.75 * n) - 1``) and one ask still open since (18
answered, 1 unanswered). This instrument reproduces that run exactly at that
stamp with that estimator, and reads n=21, 268, 726, 8264 and n=19, 6, 10, 16
at 02:20Z with its own nearest-rank p75 (the frozen refs are
``tests/fixtures/mail_latency/refs-2026-10-15T0220Z.json``). The instrument's
figures supersede the hand count's (air, 2026-10-15).

Usage::

    python3 scripts/mail_latency_census.py --split           # the split's two windows
    python3 scripts/mail_latency_census.py --since 2026-10-14
    python3 scripts/mail_latency_census.py --split --until 2026-10-15T02:20:00Z --json
    python3 scripts/mail_latency_census.py --fixture tests/fixtures/mail_latency/refs-2026-10-15T0220Z.json --split

Exit codes: 0 = report printed (no mail refs is a note); 1 = an unusable
``dispatcher`` setting for a non-split window; 2 = usage error or unreadable
input. Self-host only: the channel runs where a clone names its machine.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The dispatcher split: the stamp the worker loop began asking one seat, and
#: the seat it made the dispatcher.
SPLIT = datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc)
SPLIT_DISPATCHER = "air"
#: The pre-registered bound: a worker request answered within the hour.
WITHIN_MINUTES = 60


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _mail():
    """``tools/cc/mail.py`` by path: its decoder, its ref names, its fetch and
    its dispatcher setting are the channel's one home."""
    return _load("_mlc_mail", "tools/cc/mail.py")


#: ``run_bounded`` from this checkout's ``tools/cc/_json_safe.py``, by path:
#: ``subprocess.run`` whose timeout holds on Windows, where git is a launcher
#: whose child holds the pipe.
run_bounded = _load("_mlc_json_safe", "tools/cc/_json_safe.py").run_bounded


def parse_stamp(text: str) -> datetime:
    """An ISO stamp (``2026-10-15T02:20:00Z``) or a date (``2026-10-15``), UTC;
    raises ``ValueError`` on anything else."""
    text = str(text).strip()
    if len(text) == 10:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return datetime.strptime(text.replace("+00:00", "Z"), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _stamp_or_none(text) -> datetime | None:
    try:
        return parse_stamp(text)
    except (TypeError, ValueError):
        return None


def read_refs(root: Path) -> tuple[list[dict], dict[str, str]]:
    """Every message on every mail ref this clone holds, each once, and each
    ref's freshness: ``{ref: the stamp of its newest message}``."""
    mail = _mail()
    seen: dict[str, dict] = {}
    tips: dict[str, str] = {}
    for prefix in (mail.REMOTE_REF_PREFIX, mail.REF_PREFIX):
        out = run_bounded(["git", "for-each-ref", "--format=%(refname)", prefix], cwd=root,
                          capture_output=True, encoding="utf-8", errors="replace", env=mail.git_env(), timeout=30)
        for ref in out.stdout.split():
            shown = run_bounded(["git", "show", f"{ref}:{mail.MAIL_FILE}"], cwd=root,
                                capture_output=True, encoding="utf-8", errors="replace",
                                env=mail.git_env(), timeout=30)
            if shown.returncode != 0:
                continue
            messages, _bad = mail.decode_lines(shown.stdout)
            stamps = sorted(str(m.get("at")) for m in messages if _stamp_or_none(m.get("at")))
            tips[ref] = stamps[-1] if stamps else "-"
            for m in messages:
                seen.setdefault(str(m["id"]), m)
    return list(seen.values()), tips


def read_fixture(path: Path) -> tuple[list[dict], str | None, datetime | None]:
    """A frozen copy of the refs: ``{frozen_at, dispatcher, messages: {machine:
    [{id, type, from, at, ack}]}}`` -- the fields the pairing reads, no prose."""
    data = json.loads(path.read_text(encoding="utf-8"))
    frozen = parse_stamp(data["frozen_at"]) if data.get("frozen_at") else None
    return [m for ms in data["messages"].values() for m in ms], data.get("dispatcher"), frozen


def p75(values: list[float]) -> float | None:
    """Nearest-rank: the value at rank ``ceil(0.75 * n)`` of the sorted list."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(0.75 * len(ordered)) - 1]


def pair(messages: list[dict], dispatcher: str | None, until: datetime | None = None) -> tuple[list[dict], int]:
    """``(rows, skipped)``: each worker request with its first answer --
    ``{id, from, at, answered_at, answered_by, minutes, closed_by_asker}``,
    the answer fields None while unanswered -- and how many messages were
    skipped for a stamp that does not parse."""
    skipped = 0
    acks: dict[str, list[tuple[datetime, dict]]] = {}
    for m in messages:
        if m.get("type") == "ack" and m.get("ack"):
            t = _stamp_or_none(m.get("at"))
            if t is None:
                skipped += 1
                continue
            if until is None or t < until:
                acks.setdefault(str(m["ack"]), []).append((t, m))
    out = []
    for m in messages:
        if m.get("type") != "request" or m.get("from") == dispatcher or not m.get("id"):
            continue
        asked = _stamp_or_none(m.get("at"))
        if asked is None:
            skipped += 1
            continue
        answers = sorted(((t, a) for t, a in acks.get(str(m["id"]), []) if t >= asked), key=lambda x: x[0])
        by_asker = [a for _t, a in answers if a.get("from") == m.get("from")]
        others = [(t, a) for t, a in answers if a.get("from") != m.get("from")]
        first = others[0] if others else None
        out.append({
            "id": m["id"], "from": m.get("from"), "at": m["at"],
            "answered_at": first[1]["at"] if first else None,
            "answered_by": first[1].get("from") if first else None,
            "minutes": round((first[0] - asked).total_seconds() / 60, 1) if first else None,
            "closed_by_asker": bool(by_asker) and first is None,
        })
    return sorted(out, key=lambda r: r["at"]), skipped


def summarise(rows: list[dict], since: datetime | None, until: datetime | None,
              as_of: datetime) -> dict:
    """One window's figures, the requests asked in ``[since, until)``; an
    unanswered ask's age is taken at ``as_of`` (the report's ``--until``, or
    now), never at its window's end, so an old ask reads as old."""
    inside = [r for r in rows
              if (since is None or parse_stamp(r["at"]) >= since)
              and (until is None or parse_stamp(r["at"]) < until)]
    minutes = [r["minutes"] for r in inside if r["minutes"] is not None]
    open_rows = [r for r in inside if r["minutes"] is None and not r["closed_by_asker"]]
    unanswered = [{"id": r["id"], "from": r["from"], "at": r["at"],
                   "age_minutes": round((as_of - parse_stamp(r["at"])).total_seconds() / 60, 1)}
                  for r in open_rows]
    within = sum(1 for x in minutes if x <= WITHIN_MINUTES)
    misses = (len(minutes) - within) + sum(1 for u in unanswered if u["age_minutes"] > WITHIN_MINUTES)
    by: dict[str, int] = {}
    for r in inside:
        if r["answered_by"]:
            by[r["answered_by"]] = by.get(r["answered_by"], 0) + 1
    return {
        "since": since.strftime("%Y-%m-%dT%H:%M:%SZ") if since else None,
        "until": until.strftime("%Y-%m-%dT%H:%M:%SZ") if until else None,
        "as_of": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asked": len(inside),
        "answered": len(minutes),
        "median": round(statistics.median(minutes)) if minutes else None,
        "p75": round(p75(minutes)) if minutes else None,
        "max": round(max(minutes)) if minutes else None,
        "within_hour": within,
        "past_the_hour": misses,
        "answered_by": dict(sorted(by.items())),
        "closed_by_asker": [r["id"] for r in inside if r["closed_by_asker"]],
        "unanswered": unanswered,
    }


def report(messages: list[dict], dispatcher: str | None, windows: list[tuple[datetime | None, datetime | None]],
           as_of: datetime, until: datetime | None = None) -> dict:
    """``until`` bounds the answers (no ack at or after it counts); ``as_of``
    is where the unanswered asks' ages are taken (``until``, or now)."""
    rows, skipped = pair(messages, dispatcher, until)
    return {"dispatcher": dispatcher, "requests": len(rows), "skipped": skipped,
            "windows": [summarise(rows, s, u, as_of) for s, u in windows]}


def render(data: dict) -> str:
    lines = [f"worker requests in the refs read: {data['requests']} (the dispatcher, {data['dispatcher']!r}, "
             "is not a worker)"]
    if data.get("dispatcher_how"):
        lines.append(f"dispatcher: {data['dispatcher_how']}")
    for ref, tip in sorted(data.get("tips", {}).items()):
        lines.append(f"ref {ref}: newest message {tip}")
    if data.get("fetch"):
        lines.append(f"fetch: {data['fetch']}")
    if data["skipped"]:
        lines.append(f"skipped {data['skipped']} message(s) whose stamp does not parse")
    for w in data["windows"]:
        span = f"{w['since'] or 'the start'} .. {w['until'] or 'now'}"
        if w["answered"]:
            lines.append(f"{span}: {w['answered']} of {w['asked']} answered, median {w['median']} min, "
                         f"p75 {w['p75']} min (nearest-rank), max {w['max']} min; within the hour "
                         f"{w['within_hour']}, past it {w['past_the_hour']}")
        else:
            lines.append(f"{span}: none of {w['asked']} answered; past the hour {w['past_the_hour']}")
        if w["answered_by"]:
            lines.append("  answered by: " + ", ".join(f"{k} {v}" for k, v in w["answered_by"].items()))
        for rid in w["closed_by_asker"]:
            lines.append(f"  closed by its asker: {rid}")
        for u in w["unanswered"]:
            lines.append(f"  unanswered {u['id']} from {u['from']}, {u['age_minutes']} min old at {w['as_of']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=str(ROOT), help="the clone whose mail refs are read (default: this one)")
    ap.add_argument("--fixture", help="read a frozen refs fixture (JSON) instead of the refs")
    ap.add_argument("--no-fetch", action="store_true", help="read the refs this clone holds; do not fetch first")
    ap.add_argument("--since", help="first stamp of the window (ISO or YYYY-MM-DD, UTC)")
    ap.add_argument("--until", help="end of the window, exclusive: no ack at or after it answers, and ages are taken there")
    ap.add_argument("--split", action="store_true",
                    help="the dispatcher split's two windows, before and since 2026-10-12T19:00Z (dispatcher air)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        since = parse_stamp(args.since) if args.since else None
        until = parse_stamp(args.until) if args.until else None
    except ValueError as exc:
        print(f"mail_latency_census: a stamp is ISO (2026-10-15T02:20:00Z) or a date: {exc}", file=sys.stderr)
        return 2
    if args.split and since:
        print("mail_latency_census: --split starts its own windows; drop --since (--until ends the second)",
              file=sys.stderr)
        return 2
    if args.split and until and until <= SPLIT:
        print(f"mail_latency_census: --until {args.until} ends before the split; --split needs a later one",
              file=sys.stderr)
        return 2
    if since and until and until <= since:
        print("mail_latency_census: --until must follow --since", file=sys.stderr)
        return 2
    extra: dict[str, object] = {}
    try:
        if args.fixture:
            messages, dispatcher, frozen = read_fixture(Path(args.fixture))
            until = until or frozen
        else:
            repo = Path(args.repo).resolve()
            mail = _mail()
            if not args.no_fetch:
                ok, problem = mail.fetch_mail(repo)
                extra["fetch"] = "fetched" if ok else f"failed ({problem}); reading the refs as last fetched"
            messages, extra["tips"] = read_refs(repo)
            dispatcher, how = mail.dispatcher_setting(repo)
            extra["dispatcher_how"] = how
            if not messages:
                print(f"mail_latency_census: no mail refs in {repo} (the channel is on where `git config "
                      "espalier.machine` names the clone and `git fetch` has brought the refs)")
                return 0
    except (OSError, KeyError, ValueError) as exc:
        print(f"mail_latency_census: cannot read the input: {exc}", file=sys.stderr)
        return 2
    if args.split:
        dispatcher = SPLIT_DISPATCHER
        extra["dispatcher_how"] = f"the split's own, {SPLIT_DISPATCHER!r}, whatever espalier.toml names now"
    elif not args.fixture and dispatcher == _mail().DISPATCHER_UNUSABLE:
        print(f"mail_latency_census: the dispatcher setting is unusable: {extra.get('dispatcher_how')}",
              file=sys.stderr)
        return 1
    windows = [(None, SPLIT), (SPLIT, until)] if args.split else [(since, until)]
    data = report(messages, dispatcher, windows, until or datetime.now(timezone.utc), until)
    data.update(extra)
    print(json.dumps(data, indent=2) if args.json else render(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
