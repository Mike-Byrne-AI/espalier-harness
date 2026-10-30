#!/usr/bin/env python3
"""What each seat did on a day, read from the mail refs and the merged pull requests.

Why this exists
---------------
A dispatcher's tick reports carried the day's figures by hand, and the workers
corrected its statements: a figure carried past a compaction, a measurement
narrower than its claim, a tool's setting restated from memory. The figures a
report needs are on the mail refs and on GitHub, so this prints them, and a
report quotes the census instead of a hand's count.

What it reads
-------------
Every machine's messages on the remote-tracking mail refs, fetched first
(``--no-fetch`` reads what is here), as ``tools/cc/mail.py::read_mail`` folds
them for the board; the merged pull requests ``gh pr list`` gives; the Session
Log fragment names in the folder ``tools/cc/_record_fragments.py`` names. A
fixture (``--fixture``) is a frozen copy of the same, the fields this reads and
no message prose. A read that failed is said in every form of the output, the
row and the JSON included, never printed as a zero.

Per seat per UTC day in ``[since, until)``, one row:

* **lanes merged**: the pull requests merged that day whose branch's seat is
  this one, by the latest claim or release naming the lane
  (``tools/cc/mail.py::lane_seats``); a merged branch no message names is
  counted as unattributed, and a list at its limit is said.
* **assigns received**: the assigns the fold counts (the dispatcher's, when one
  is named) stamped that day and given to this seat, re-sends included; a
  day's assigns are counted on the day they were sent.
* **jobs closed**, by the rule that closed each, from the fold's own record
  (``tools/cc/mail.py::live_assignments``, its ``closed`` list) over the
  messages stamped before ``until``, so the rules have one home: ``ack`` (a
  release naming the assign), ``lane`` (the assign's own lane released),
  ``claim`` (the seat's own claim on the shipped lane named the job's ids). A
  job counts on the day of the release that closed it, so a day's closures can
  include jobs given on an earlier day.
* **re-assigned after a close**: for each job the claim rule closed, the
  first later assign of the same job (its lane, classes and ids), counted on
  that assign's day for the seat it names, each job named and split in two: a
  job naming a ledger row (``tools/cc/ledger_row.py::_ROW_ID_RE``), the shape
  the strike-keyed rule waits on, and the rest, chiefly a pack assigned by its
  id, which closes at its first shipped lane and is re-sent for its next wave.
* **releases naming an assign**: the releases the seat sent naming an assign
  by its id, each a hand's work whatever the fold did first, split in two: the
  ones that closed a live job (a dispatcher's decision: a re-assign, a void, a
  hand-back) and the ones that named a job already closed (hand work the third
  rule made needless, the figure the pre-registered hand-release measure reads).
* **requests** the seat sent that day and how many were answered, with the
  median minutes to the answer (``scripts/mail_latency_census.py::pair``, which
  leaves the dispatcher's own requests out).
* **Session Log rows**: the fragment names for the seat and the day. A name's
  date is its writer's local day, a row parked on a records ref is not in the
  tree, and fragments older than the newest few are archived; the report says
  all three, and the oldest day the tree holds.
* **START**: the seat's messages that day whose text carries the word (the
  tier-run announcement, anywhere in a text).
* **redirect:**, **shelved:** and **gridlock:**: the seat's messages that day
  whose text opens with the marker (``MARKERS``, on the text as the driver
  stores it, stripped on send), as the operator-call rule reads ``OPERATOR CALL:``
  (``tools/cc/mail.py::is_operator_call``). The briefs and the assigns quote
  the same words mid-text, so a mention anywhere is prose, not a use: 8 of 9
  ``redirect:`` and 5 of 5 ``shelved:`` mentions on the refs by 2026-10-30
  were quotations (``DEF-5029``). A ``gridlock:`` ack from the dispatcher
  (every seat's where none is named) is a ruling on a gridlock
  (``tools/cc/seat.py::SELF_HOST_GRIDLOCK``, one ruling per ack); a note or a
  request opening with the word is not, and the row names each ruling's id
  beside the count, in time order, so the operator can find the ruling to
  reverse (the protocol's falsifier).

The dispatcher's own row adds what it sent: its assigns, and of those the new
jobs (an assign of a job already live is a re-send, not a new job); and, of the
day's worker requests, the ones it answered. Per seat, the jobs still live at ``until`` (now, when ``until`` is
later). ``--seat S --date YYYY-MM-DD --as-row`` prints that seat's row for that
UTC day as a Session Log row body, the figures only, and writes nothing.

``--jobs N`` ends the window where the dispatcher gives its next new job after
the Nth since ``--since``, so a measure counted in jobs (from a merge's stamp
until 25 new jobs) reads its window from the tool; the JSON
lists each new job's stamp in ``new_jobs``.

Usage::

    python3 scripts/seat_day_census.py                          # today so far, UTC, every seat
    python3 scripts/seat_day_census.py --since 2026-10-18 --until 2026-10-19 --json
    python3 scripts/seat_day_census.py --seat win --date 2026-10-18 --as-row
    python3 scripts/seat_day_census.py --since 2026-10-21T09:15:00Z --jobs 25
    python3 scripts/seat_day_census.py --fixture tests/fixtures/seat_day/refs-2026-10-18.json --since 2026-10-18

Exit codes: 0 = report printed (no mail refs is a note); 1 = an unusable
``dispatcher`` setting; 2 = usage error, a seat no message names, or input that
cannot be read. Self-host only: the channel runs where a clone names its machine.
"""
from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import re
import statistics
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: The markers a seat opens a message with: ``redirect:`` (an ack that re-aims
#: a seat) and ``shelved:`` (a note that shelves a lane) when it moves off a
#: job, and ``gridlock:`` (the dispatcher's ruling ack on a gridlock, the
#: brief's sentence in ``tools/cc/seat.py::SELF_HOST_GRIDLOCK``). Read where
#: the text opens with the marker, never anywhere in it: the briefs and the
#: assigns quote these words mid-text (``DEF-5029``), as ``OPERATOR CALL:`` is
#: quoted and read at the opening alone (``tools/cc/mail.py::is_operator_call``);
#: ``gridlock:`` counts on an ack from the dispatcher alone, as that rule
#: counts a request alone. ``tests/test_seat.py`` holds the brief's word to
#: this table.
MARKERS = {"redirect": "redirect:", "shelved": "shelved:", "gridlock": "gridlock:"}
#: Every counted word, in the order a row prints them: the seats' START (a
#: word anywhere in a text: the tier-run announcement, which never opens a
#: message), then the markers.
WORDS = ("start", *MARKERS)
START_RE = re.compile(r"\bSTART\b")
#: The closing rules the fold records, in the order a row prints them.
RULES = ("claim", "lane", "ack")
#: The merged pull requests' read limit; the read's argv spells it.
GH_LIMIT = 200
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@functools.lru_cache(maxsize=None)
def _mail():
    """``tools/cc/mail.py`` by path: its reader, its fold and its dispatcher
    setting are the channel's one home."""
    return _load("_sdc_mail", "tools/cc/mail.py")


@functools.lru_cache(maxsize=None)
def _latency():
    """``scripts/mail_latency_census.py`` by path: its stamp parser and its
    request-to-answer pairing."""
    return _load("_sdc_latency", "scripts/mail_latency_census.py")


@functools.lru_cache(maxsize=None)
def _ledger():
    """``tools/cc/ledger_row.py`` by path: what a ledger row's id is."""
    return _load("_sdc_ledger", "tools/cc/ledger_row.py")


@functools.lru_cache(maxsize=None)
def _fragments():
    """``tools/cc/_record_fragments.py`` by path: the Session Log folder and
    the pattern of its names."""
    return _load("_sdc_fragments", "tools/cc/_record_fragments.py")


#: ``run_bounded`` from this checkout's ``tools/cc/_json_safe.py``, by path:
#: ``subprocess.run`` whose timeout holds on Windows, where a launcher's child
#: holds the pipe.
run_bounded = _load("_sdc_json_safe", "tools/cc/_json_safe.py").run_bounded


def read_fixture(path: Path) -> dict:
    """A frozen copy: ``{frozen_at, dispatcher, messages: {machine: [...]},
    merged: [{number, headRefName, mergedAt}], session_log: [names]}``. A
    message's ``from`` is its machine unless it says otherwise; its counted
    words are booleans in place of its text."""
    data = json.loads(path.read_text(encoding="utf-8"))
    by_machine = {machine: [dict(m, **{"from": m.get("from") or machine}) for m in ms]
                  for machine, ms in data["messages"].items()}
    return {"by_machine": by_machine, "dispatcher": data.get("dispatcher"),
            "frozen_at": data.get("frozen_at"), "merged": data.get("merged"),
            "session_log": list(data.get("session_log") or []), "dispatcher_how": "the fixture's"}


def read_live(repo: Path, fetch: bool) -> dict:
    """The refs, the merged pull requests and the Session Log names of
    ``repo``. A mail read git refuses raises the channel's ``Unresolvable``;
    a merged-pull-request read that fails is a note and an unread list."""
    mail = _mail()
    out: dict = {}
    if fetch:
        ok, problem = mail.fetch_mail(repo)
        out["fetch"] = "fetched" if ok else f"failed ({problem}); the mail is as last fetched"
    by_machine, skipped = mail.read_mail(repo)
    out["by_machine"] = by_machine
    out["skipped"] = sum(skipped.values())
    out["dispatcher"], out["dispatcher_how"] = mail.dispatcher_setting(repo)
    try:
        gh = run_bounded(["gh", "pr", "list", "--state", "merged", "--limit", str(GH_LIMIT), "--json",
                          "number,headRefName,mergedAt,labels"], cwd=repo, capture_output=True, encoding="utf-8",
                         errors="replace", timeout=60)
        out["merged"] = json.loads(gh.stdout) if gh.returncode == 0 else None
        if gh.returncode != 0:
            out["merged_note"] = f"gh pr list failed: {(gh.stderr or '').strip()[:200]}"
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        out["merged"], out["merged_note"] = None, f"gh pr list could not run: {exc}"
    log = repo / _fragments().SESSION_LOG_DIR
    out["session_log"] = sorted(p.name for p in log.glob("*.md")) if log.is_dir() else []
    return out


def _words(m: dict, dispatcher: str | None = None) -> dict[str, bool]:
    """The counted words a message carries: its fixture booleans, else its
    text -- START anywhere in it, a marker where the text opens with it, as
    the driver stores it (stripped on send; ``tools/cc/mail.py::is_operator_call``
    reads ``OPERATOR CALL:`` the same way, with no strip of its own), and
    ``gridlock:`` on an ack from ``dispatcher`` alone (any seat's where none
    is named)."""
    text = str(m.get("text") or "")
    hits = {"start": bool(START_RE.search(text))}
    hits.update({k: text.startswith(marker) for k, marker in MARKERS.items()})
    ruling = m.get("type") == "ack" and (dispatcher is None or str(m.get("from")) == dispatcher)
    hits["gridlock"] = hits["gridlock"] and ruling
    return {k: bool(m.get(k)) or hits[k] for k in WORDS}


def session_log_names(names: list[str]) -> list[tuple[str, str]]:
    """``(date, seat)`` for each Session Log fragment name the loader's pattern
    reads (``tools/cc/_record_fragments.py::SESSION_LOG_NAME_RE``)."""
    out = []
    for name in names:
        m = _fragments().SESSION_LOG_NAME_RE.match(name)
        if m:
            out.append((m.group(1), m.group(3)))
    return out


def _counted_assigns(by_machine: dict[str, list[dict]], dispatcher: str | None) -> list[dict]:
    """The assigns the fold reads: the dispatcher's when one is named, every
    machine's when none is."""
    return [m for machine, ms in by_machine.items() for m in ms
            if m.get("type") == "assign" and (not dispatcher or machine == dispatcher)]


def _new_row(seat: str, day: str) -> dict:
    return {"seat": seat, "day": day, "lanes_merged": [], "assigns_received": 0,
            "closed": dict.fromkeys(RULES, 0), "reassigned_after_close": 0, "reassigned_rows": [],
            "reassigned_packs": [], "hand_releases": 0, "hand_releases_closing": 0, "requests": 0,
            "answered": 0, "median_minutes": None, "session_log_rows": 0, **dict.fromkeys(WORDS, 0),
            # The rulings' own ids, so the day row names what the operator can reverse.
            "gridlock_ids": []}


#: What the dispatcher sent on a day, by the census's own counts.
SENDS = ("assigns_sent", "jobs_given", "requests_answered")


def _names_a_row(a: dict) -> bool:
    """Whether a job names a ledger row among its ids."""
    rx = _ledger()._ROW_ID_RE
    return any(rx.fullmatch(i) for i in _mail()._str_list((a.get("re") or {}).get("ids")))


def _job_name(mail, a: dict) -> str:
    """A job as a reader names it: its ids, else its lane, else its classes."""
    re_ = a.get("re") or {}
    return (" ".join(mail._str_list(re_.get("ids"))) or str(re_.get("lane") or "")
            or " ".join(mail._str_list(re_.get("classes"))))


def census(src: dict, since: datetime, until: datetime, now: datetime | None = None) -> dict:
    """The rows for every seat and UTC day in ``[since, until)``, the jobs live
    at ``until`` (or ``now``, when that is earlier) per seat, the dispatcher's
    sends, and the totals."""
    mail, lat = _mail(), _latency()
    stamp = lat.parse_stamp
    now = now or datetime.now(timezone.utc)
    days = []
    day = since.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < until:
        days.append(day.strftime("%Y-%m-%d"))
        day += timedelta(days=1)

    def day_of(at) -> str | None:
        try:
            t = stamp(str(at))
        except (TypeError, ValueError):
            return None
        return t.strftime("%Y-%m-%d") if since <= t < until else None

    until_text = until.strftime("%Y-%m-%dT%H:%M:%SZ")
    before = {machine: [m for m in ms if str(m.get("at") or "") < until_text]
              for machine, ms in src["by_machine"].items()}
    dispatcher = src.get("dispatcher")
    closed: list = []
    live = mail.live_assignments(before, dispatcher, closed=closed)
    lanes = mail.lane_seats(before)
    flat = [m for ms in before.values() for m in ms]
    pairs, _skipped = lat.pair(flat, dispatcher, until)
    merged = src.get("merged")

    rows: dict[tuple[str, str], dict] = {}

    def row(seat: str, d: str) -> dict:
        return rows.setdefault((seat, d), _new_row(seat, d))

    assigns = sorted(_counted_assigns(before, dispatcher), key=lambda a: str(a.get("at") or ""))
    assign_ids = {str(a.get("id")) for a in assigns}
    sends = {d: dict.fromkeys(SENDS, 0) for d in days}
    closed_at = {str(a.get("id")): str(r.get("at") or "") for a, r, _rule in closed}
    latest: dict = {}
    new_jobs: list[str] = []
    for a in assigns:
        key = mail._job_key(a.get("re") or {})
        before_it = latest.get(key)
        # A new job unless it re-sends one still live: the job's last assign closed before it, or none.
        new = before_it is None or closed_at.get(str(before_it.get("id")), "~") <= str(a.get("at") or "")
        latest[key] = a
        d = day_of(a.get("at"))
        if d is not None and (a.get("re") or {}).get("seat"):
            row(str(a["re"]["seat"]), d)["assigns_received"] += 1
            sends[d]["assigns_sent"] += 1
            sends[d]["jobs_given"] += new
            if new:
                new_jobs.append(str(a.get("at") or ""))
    # In time order across the refs, so a row's ruling ids read oldest first.
    for m in sorted(flat, key=lambda x: str(x.get("at") or "")):
        d = day_of(m.get("at"))
        if d is None:
            continue
        if m.get("type") == "release" and str(m.get("ack") or "") in assign_ids:
            row(str(m.get("from")), d)["hand_releases"] += 1
        for k, hit in _words(m, dispatcher).items():
            if hit:
                r = row(str(m.get("from")), d)
                r[k] += 1
                if k == "gridlock":
                    r["gridlock_ids"].append(str(m.get("id")))
    for assign, release, rule in closed:
        d = day_of(release.get("at"))
        seat = (assign.get("re") or {}).get("seat")
        if d is not None and seat:
            row(str(seat), d)["closed"][rule] += 1
        if d is not None and rule == "ack":
            row(str(release.get("from")), d)["hand_releases_closing"] += 1
        if rule != "claim":
            continue
        key = mail._job_key(assign.get("re") or {})
        again = next((a for a in assigns if str(a.get("at") or "") > str(release.get("at") or "")
                      and mail._job_key(a.get("re") or {}) == key), None)
        dd = day_of(again.get("at")) if again else None
        if dd is not None and (again.get("re") or {}).get("seat"):
            r = row(str(again["re"]["seat"]), dd)
            r["reassigned_after_close"] += 1
            r["reassigned_rows" if _names_a_row(again) else "reassigned_packs"].append(_job_name(mail, again))
    minutes: dict[tuple[str, str], list[float]] = {}
    for p in pairs:
        d = day_of(p["at"])
        if d is None:
            continue
        r = row(str(p["from"]), d)
        r["requests"] += 1
        if p["minutes"] is not None:
            r["answered"] += 1
            minutes.setdefault((str(p["from"]), d), []).append(p["minutes"])
            if dispatcher and p.get("answered_by") == dispatcher and d in sends:
                sends[d]["requests_answered"] += 1
    for key, values in minutes.items():
        rows[key]["median_minutes"] = round(statistics.median(values), 1)
    unattributed = []
    for pr in merged or []:
        d = day_of(pr.get("mergedAt"))
        if d is None:
            continue
        # The claim first, else the seat label the ship driver stamped on the
        # pull request (the loader's one attribution, DEF-4044).
        seat = _fragments().lane_seat(pr, lanes)
        if seat:
            row(seat, d)["lanes_merged"].append(int(pr["number"]))
        else:
            unattributed.append(int(pr["number"]))
    names = session_log_names(src.get("session_log") or [])
    for d, seat in names:
        if d in days:
            row(seat, d)["session_log_rows"] += 1
    if merged is None:
        for r in rows.values():
            r["lanes_merged"] = None

    live_by_seat: dict[str, list[str]] = {}
    for a in live:
        seat = (a.get("re") or {}).get("seat")
        if seat:
            live_by_seat.setdefault(str(seat), []).append(str(a.get("id")))
    ordered = [rows[k] for k in sorted(rows)]
    seats = sorted({str(s) for s in before} | {str(m.get("from")) for m in flat if m.get("from")}
                   | {str((a.get("re") or {}).get("seat")) for a in assigns if (a.get("re") or {}).get("seat")})
    totals = {**{k: sum(s[k] for s in sends.values()) for k in SENDS},
              "assigns_received": sum(r["assigns_received"] for r in ordered),
              "closed": {rule: sum(r["closed"][rule] for r in ordered) for rule in RULES},
              "reassigned_after_close": sum(r["reassigned_after_close"] for r in ordered),
              "reassigned_rows": sum(len(r["reassigned_rows"]) for r in ordered),
              "reassigned_packs": sum(len(r["reassigned_packs"]) for r in ordered),
              "hand_releases": sum(r["hand_releases"] for r in ordered),
              "hand_releases_by_dispatcher": sum(r["hand_releases"] for r in ordered if r["seat"] == dispatcher),
              "hand_releases_closing": sum(r["hand_releases_closing"] for r in ordered),
              "hand_releases_of_closed_jobs": sum(r["hand_releases"] - r["hand_releases_closing"] for r in ordered),
              "live": sum(len(v) for v in live_by_seat.values()),
              "lanes_merged": None if merged is None else sum(len(r["lanes_merged"] or []) for r in ordered),
              "unattributed_merges": None if merged is None else len(unattributed),
              "requests": sum(r["requests"] for r in ordered),
              "answered": sum(r["answered"] for r in ordered),
              "session_log_rows": sum(r["session_log_rows"] for r in ordered),
              **{k: sum(r[k] for r in ordered) for k in WORDS}}
    oldest = min((d for d, _seat in names), default=None)
    return {"since": since.strftime("%Y-%m-%dT%H:%M:%SZ"), "until": until_text, "days": days,
            "so_far": until > now, "live_at": min(until, now).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "dispatcher": dispatcher, "seats": seats, "rows": ordered, "new_jobs": new_jobs,
            "dispatcher_sends": sends, "live": dict(sorted(live_by_seat.items())),
            "unattributed_merges": None if merged is None else sorted(unattributed), "totals": totals,
            "merged_read": merged is not None,
            "merged_at_limit": merged is not None and len(merged) >= GH_LIMIT,
            "session_log_oldest": oldest}


def _again(r: dict) -> str:
    """The jobs re-sent after the claim rule closed them, rows apart from the rest."""
    parts = [f"rows: {', '.join(r['reassigned_rows'])}" if r["reassigned_rows"] else "",
             f"packs: {', '.join(r['reassigned_packs'])}" if r["reassigned_packs"] else ""]
    named = "; ".join(part for part in parts if part)
    return f" ({named})" if named else ""


def _hand(r: dict) -> str:
    """A row's releases naming an assign, both halves named."""
    return (f"releases naming an assign {r['hand_releases']} ({r['hand_releases_closing']} closed a live job, "
            f"{r['hand_releases'] - r['hand_releases_closing']} named a job already closed)")


def _words_line(r: dict) -> str:
    """A row's counted words, the gridlock rulings named by id after their
    count (none: the count alone)."""
    ids = r.get("gridlock_ids") or []
    named = f" ({', '.join(ids)})" if ids else ""
    return (f"START {r['start']}, redirect: {r['redirect']}, shelved: {r['shelved']}, "
            f"gridlock: {r['gridlock']}{named}")


def as_row(data: dict, seat: str, day: str, extra: dict | None = None) -> str:
    """One Session Log row body for ``seat`` on the UTC ``day``: the figures
    only, an unread read said as unread. The dispatcher's row adds what it sent."""
    extra = extra or {}
    r = next((x for x in data["rows"] if x["seat"] == seat and x["day"] == day), None) or _new_row(seat, day)
    notes = []
    if data["so_far"]:
        notes.append("the day so far")
    if str(extra.get("fetch", "")).startswith("failed"):
        notes.append(f"mail {extra['fetch']}")
    oldest = data.get("session_log_oldest")
    if extra.get("skipped"):
        notes.append(f"{extra['skipped']} mail line(s) unread")
    if oldest and day < oldest:
        notes.append(f"Session Log rows before {oldest} are archived")
    head = f"UTC day{'; ' + '; '.join(notes) if notes else ''}"
    if not data["merged_read"] or r["lanes_merged"] is None:
        merged = f"lanes merged unread ({extra.get('merged_note') or 'no list'})"
    else:
        listed = ", ".join(f"#{n}" for n in r["lanes_merged"])
        merged = f"lanes merged {len(r['lanes_merged'])}{f' ({listed})' if listed else ''}"
    words = _words_line(r)
    logs = f"Session Log rows {r['session_log_rows']}"
    hand = _hand(r)
    if seat == data["dispatcher"]:
        s = data["dispatcher_sends"].get(day) or dict.fromkeys(SENDS, 0)
        # The releases it owes: the jobs live at the day's end, per seat.
        live_by_seat = {k: len(v) for k, v in sorted(data["live"].items()) if v}
        owed = (f"jobs live at {data['live_at']} {sum(live_by_seat.values())}"
                + (f" ({', '.join(f'{k} {n}' for k, n in live_by_seat.items())})" if live_by_seat else ""))
        body = (f"assigns sent {s['assigns_sent']} ({s['jobs_given']} new jobs); {hand}; the day's worker "
                f"requests it answered {s['requests_answered']}; {owed}; {merged}; {logs}; {words}.")
    else:
        c = r["closed"]
        median = f", median {r['median_minutes']} min to an answer" if r["median_minutes"] is not None else ""
        live = len(data["live"].get(seat, []))
        body = (f"{merged}; assigns received {r['assigns_received']}; jobs closed that day, by their release, "
                f"{sum(c.values())} ({c['claim']} by its own claim on the shipped lane, {c['lane']} by the "
                f"assign's lane, {c['ack']} by a release naming the assign), re-assigned after a close "
                f"{r['reassigned_after_close']}{_again(r)}; jobs live at {data['live_at']} {live}; {hand}; "
                f"requests {r['requests']}, {r['answered']} answered{median}; {logs}; {words}.")
    return f"| {day} | **{seat}: the day's figures (seat-day census, {head})** | {body} |"


def render(data: dict, extra: dict) -> str:
    lines = [f"seat-day census, {data['since']} .. {data['until']} (UTC days{', so far' if data['so_far'] else ''}), "
             f"dispatcher {data['dispatcher']!r}"]
    if extra.get("dispatcher_how"):
        lines.append(f"dispatcher: {extra['dispatcher_how']}")
    if extra.get("jobs_window"):
        lines.append(f"window: {extra['jobs_window']}")
    if extra.get("fetch"):
        lines.append(f"fetch: {extra['fetch']}")
    if extra.get("skipped"):
        lines.append(f"skipped {extra['skipped']} mail line(s) that do not parse; their messages are not counted")
    for machine, tip in sorted(extra.get("tips", {}).items()):
        lines.append(f"ref {machine}: newest message {tip}")
    if not data["merged_read"]:
        lines.append(f"merged pull requests: unread ({extra.get('merged_note', 'no list')})")
    elif data["merged_at_limit"]:
        lines.append(f"merged pull requests: the list is at its limit ({GH_LIMIT}); older merges may be missing")
    for r in data["rows"]:
        c = r["closed"]
        median = f", median {r['median_minutes']} min" if r["median_minutes"] is not None else ""
        merged = "unread" if r["lanes_merged"] is None else len(r["lanes_merged"])
        lines.append(f"{r['day']} {r['seat']}: merged {merged}, assigns {r['assigns_received']}, "
                     f"closed {sum(c.values())} (claim {c['claim']}, lane {c['lane']}, ack {c['ack']}), "
                     f"re-assigned after a close {r['reassigned_after_close']}{_again(r)}, {_hand(r)}, requests "
                     f"{r['requests']} ({r['answered']} answered{median}), Session Log rows {r['session_log_rows']}, "
                     f"{_words_line(r)}")
    for d, s in data["dispatcher_sends"].items():
        lines.append(f"{d} {data['dispatcher']} sent: assigns {s['assigns_sent']} ({s['jobs_given']} new jobs), "
                     f"the day's worker requests it answered {s['requests_answered']}")
    for seat, ids in data["live"].items():
        lines.append(f"live at {data['live_at']}, {seat}: {len(ids)} ({', '.join(ids)})")
    t = data["totals"]
    merged_total = "unread" if t["lanes_merged"] is None else f"{t['lanes_merged']} (unattributed {t['unattributed_merges']})"
    lines.append(f"totals: assigns {t['assigns_received']} (sent {t['assigns_sent']}, {t['jobs_given']} new jobs), "
                 f"releases naming an assign {t['hand_releases']} (the dispatcher's {t['hand_releases_by_dispatcher']}; "
                 f"{t['hand_releases_closing']} closed a live job, {t['hand_releases_of_closed_jobs']} named a job "
                 f"already closed), closed claim {t['closed']['claim']} lane "
                 f"{t['closed']['lane']} ack {t['closed']['ack']}, re-assigned after a close "
                 f"{t['reassigned_after_close']} (rows {t['reassigned_rows']}, packs {t['reassigned_packs']}), "
                 f"live {t['live']}, merged {merged_total}, requests {t['requests']} ({t['answered']} answered), "
                 f"Session Log rows {t['session_log_rows']}")
    lines.append("note: assigns and releases count on the day they were sent, closures on the day of the release "
                 "that closed them, so a day's closures can be of jobs given before it")
    lines.append("note: a Session Log name's date is its writer's local day, a row parked on a records ref is not "
                 "in the tree, and older rows are archived"
                 + (f" (the tree's oldest: {data['session_log_oldest']})" if data["session_log_oldest"] else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=str(ROOT), help="the clone whose refs are read (default: this one)")
    ap.add_argument("--fixture", help="read a frozen fixture (JSON) instead of the refs")
    ap.add_argument("--no-fetch", action="store_true", help="read the refs this clone holds; do not fetch first")
    ap.add_argument("--since", help="the first UTC day (YYYY-MM-DD, or an ISO stamp; default: today)")
    ap.add_argument("--until", help="the end, exclusive (default: the fixture's freeze, or now)")
    ap.add_argument("--seat", help="with --as-row: the seat whose row is printed")
    ap.add_argument("--date", help="with --as-row: the UTC day (YYYY-MM-DD) whose row is printed")
    ap.add_argument("--as-row", action="store_true", help="print one Session Log row body; write nothing")
    ap.add_argument("--jobs", type=int, help="end the window where the next new job after the Nth since --since "
                    "is given (a measure counted in jobs)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    lat = _latency()
    if args.as_row and not (args.seat and args.date):
        print("seat_day_census: --as-row needs --seat and --date", file=sys.stderr)
        return 2
    if args.seat and not args.as_row:
        print("seat_day_census: --seat names the row --as-row prints; the report lists every seat",
              file=sys.stderr)
        return 2
    if args.date and (args.since or args.until):
        print("seat_day_census: --date is one UTC day; give it alone, or --since and --until", file=sys.stderr)
        return 2
    if args.jobs is not None and (args.jobs < 1 or not args.since or args.until or args.date):
        print("seat_day_census: --jobs N (N of 1 or more) ends a window that --since opens; give it with --since "
              "and without --until or --date", file=sys.stderr)
        return 2
    if args.date and not DAY_RE.match(args.date):
        print(f"seat_day_census: --date is a UTC day, YYYY-MM-DD, not {args.date!r}", file=sys.stderr)
        return 2
    try:
        since = lat.parse_stamp(args.date or args.since) if (args.date or args.since) else None
        until = lat.parse_stamp(args.until) if args.until else None
    except ValueError as exc:
        print(f"seat_day_census: a day is YYYY-MM-DD or an ISO stamp: {exc}", file=sys.stderr)
        return 2
    extra: dict = {}
    try:
        if args.fixture:
            src = read_fixture(Path(args.fixture))
            if until is None and src.get("frozen_at"):
                until = lat.parse_stamp(src["frozen_at"])
        else:
            repo = Path(args.repo).resolve()
            src = read_live(repo, fetch=not args.no_fetch)
            if src["dispatcher"] == _mail().DISPATCHER_UNUSABLE:
                print(f"seat_day_census: the dispatcher setting is unusable: {src['dispatcher_how']}",
                      file=sys.stderr)
                return 1
            if not src["by_machine"]:
                print(f"seat_day_census: no mail refs in {repo} (the channel is on where `git config "
                      "espalier.machine` names the clone and `git fetch` has brought the refs)")
                return 0
            extra["tips"] = {machine: (ms[-1].get("at") if ms else "-") for machine, ms in src["by_machine"].items()}
    except _mail().Unresolvable as exc:
        print(f"seat_day_census: the mail refs cannot be read: {exc}", file=sys.stderr)
        return 2
    except (OSError, KeyError, ValueError) as exc:
        print(f"seat_day_census: cannot read the input: {exc}", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    since = since or now.replace(hour=0, minute=0, second=0, microsecond=0)
    if args.date:
        until = since + timedelta(days=1)
    until = until or now
    if until <= since:
        print("seat_day_census: --until must follow --since", file=sys.stderr)
        return 2
    for key in ("fetch", "dispatcher_how", "merged_note", "skipped"):
        if src.get(key):
            extra[key] = src[key]
    data = census(src, since, until, now)
    if args.jobs is not None:
        stamps = data["new_jobs"]
        if len(stamps) > args.jobs:
            until = lat.parse_stamp(stamps[args.jobs])
            data = census(src, since, until, now)
            extra["jobs_window"] = (f"--jobs {args.jobs}: it ends at {stamps[args.jobs]}, where the next new job was "
                                    f"given, so it holds {args.jobs} new jobs")
        else:
            extra["jobs_window"] = (f"--jobs {args.jobs}: only {len(stamps)} new jobs since {data['since']}, so the "
                                    f"window runs to {data['until']} and the count is not yet complete")
    if args.as_row:
        if args.seat not in data["seats"]:
            print(f"seat_day_census: no message of the refs read names the seat {args.seat!r} "
                  f"(seats: {', '.join(data['seats'])})", file=sys.stderr)
            return 2
        print(as_row(data, args.seat, since.strftime("%Y-%m-%d"), extra))
    elif args.json:
        print(json.dumps({**data, **extra}, indent=2))
    else:
        print(render(data, extra))
    return 0


if __name__ == "__main__":
    sys.exit(main())
