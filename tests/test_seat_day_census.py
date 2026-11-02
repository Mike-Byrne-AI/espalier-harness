# pytest-marker: default-unit  (a frozen-fixture census and planted messages; no git, no gh)
"""Pins ``scripts/seat_day_census.py``: what each seat did on a UTC day, read from
the mail refs and the merged pull requests, so a dispatcher's report quotes the
day's figures instead of carrying them by hand.

The live refs move every minute, so the figures are pinned on a fixture frozen
from them at 2026-10-19T00:00Z (the fields the census reads, no prose; the
merged pull requests, requests and Session Log names of 2026-10-18 alone, the
assigns, claims and releases of 10-17 and 10-18). Read by the fold the census
ships beside, the UTC day of 2026-10-18 holds 25 assigns sent to the three
worker seats, all 25 new jobs; 27 closures, counted on their release's day (24
by the seat's own claim on the shipped lane, 1 by an assign's own lane, 2 by a
release naming the assign; four of the 27 closed jobs given on 10-17); 2 jobs
live at the day's end; and 28 releases the dispatcher sent by hand naming an
assign, 2 of which closed a live job. The 25 assigns of that day, read as a
cohort, close 21 by claim, 1 by lane and 1 by a release naming the assign,
with 2 live; the old rules read the same cohort as 22 by hand, 1 by lane and 2
live (the pack's Task 0 item 1), so the difference is the third rule's. Each
rule the census states has a planted case that reds when the rule is broken.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "seat_day_census.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "seat_day" / "refs-2026-10-18.json"

if not MODULE_PATH.is_file():  # pragma: no cover - adopter tree
    pytest.skip("scripts/seat_day_census.py is self-host dev tooling", allow_module_level=True)


def _load():
    spec = importlib.util.spec_from_file_location("seat_day_census", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


census_mod = _load()
DAY = datetime(2026, 10, 18, tzinfo=timezone.utc)
NEXT = datetime(2026, 10, 19, tzinfo=timezone.utc)


def _m(machine: str, kind: str, at: str, mid: str, **kw) -> dict:
    """A planted message: the fields the census reads."""
    m = {"id": mid, "type": kind, "from": machine, "at": at}
    re_ = {k: kw.pop(k) for k in ("lane", "seat", "ids") if k in kw}
    if re_:
        m["re"] = re_
    m.update(kw)
    return m


def _src(*messages: dict, merged: list[dict] | None = None, session_log: list[str] | None = None) -> dict:
    by_machine: dict[str, list[dict]] = {}
    for m in messages:
        by_machine.setdefault(m["from"], []).append(m)
    return {"by_machine": by_machine, "dispatcher": "air", "merged": merged or [], "session_log": session_log or []}


class TestTheFixtureReadsTheDaysFigures:
    """The frozen refs of 2026-10-18 read to the figures the module docstring
    states; a change to the fold, the pairing or the attribution moves them."""

    def test_the_days_assigns_closures_and_live_jobs(self):
        """Dies to: closures counted on the assign's day instead of the
        release's, the dispatcher filter dropped, or the live set read at
        another stamp."""
        data = census_mod.census(census_mod.read_fixture(FIXTURE), DAY, NEXT)
        t = data["totals"]
        assert t["assigns_received"] == 25
        assert t["closed"] == {"claim": 24, "lane": 1, "ack": 2}
        assert data["live"] == {"win": ["20261018T084922Z-air-92505b"], "win-2": ["20261018T190351Z-air-b85659"]}
        by_seat = {r["seat"]: r["assigns_received"] for r in data["rows"]}
        assert by_seat == {"air": 0, "air-work": 10, "win": 8, "win-2": 7}
        # A closure belongs to the seat the job was given to, never the release's sender.
        assert {r["seat"]: r["closed"] for r in data["rows"]} == {
            "air": {"claim": 0, "lane": 0, "ack": 0}, "air-work": {"claim": 10, "lane": 1, "ack": 0},
            "win": {"claim": 8, "lane": 0, "ack": 1}, "win-2": {"claim": 6, "lane": 0, "ack": 1}}

    def test_every_merge_of_the_day_is_attributed_to_its_lanes_seat(self):
        """Dies to: a merged branch matched to a seat by anything but the latest
        claim or release naming its lane."""
        data = census_mod.census(census_mod.read_fixture(FIXTURE), DAY, NEXT)
        assert data["totals"]["lanes_merged"] == 28
        assert data["unattributed_merges"] == []
        assert {r["seat"]: len(r["lanes_merged"]) for r in data["rows"] if r["lanes_merged"]} == {
            "air-work": 12, "win": 9, "win-2": 7}

    def test_as_row_prints_one_session_log_row_and_writes_nothing(self, tmp_path, monkeypatch, capsys):
        """The row a day's writer reads: the figures only, in the fragments'
        shape, and no file. Dies to: a row written to disk, or a figure typed
        into the body that the census did not read."""
        work = tmp_path / "cwd"
        work.mkdir()
        monkeypatch.chdir(work)
        rc = census_mod.main(["--fixture", str(FIXTURE), "--seat", "win", "--date", "2026-10-18", "--as-row"])
        out = capsys.readouterr().out.strip()
        assert rc == 0
        assert out.startswith("| 2026-10-18 | **win: the day's figures (seat-day census, UTC day)** | ")
        assert out.endswith(" |")
        assert "assigns received 8;" in out and "jobs live at 2026-10-19T00:00:00Z 1;" in out
        assert list(work.iterdir()) == []

    def test_the_text_form_prints_the_measures_figures(self, capsys):
        """TP-703's line 6 reads the text form, so its figures are pinned there,
        not only in the JSON. Dies to: the totals line, a seat's line or the
        dispatcher's sends line printing another count under the same words."""
        assert census_mod.main(["--fixture", str(FIXTURE), "--since", "2026-10-18"]) == 0
        out = capsys.readouterr().out
        assert "2026-10-18 air sent: assigns 25 (25 new jobs), the day's worker requests it answered 23" in out
        assert ("totals: assigns 25 (sent 25, 25 new jobs), releases naming an assign 28 (the dispatcher's 28; "
                "2 closed a live job, 26 named a job already closed), closed claim 24 lane 1 ack 2") in out, out
        assert "re-assigned after a close 0 (rows 0, packs 0)" in out
        assert ("2026-10-18 air: merged 0, assigns 0, closed 0 (claim 0, lane 0, ack 0), re-assigned after a close 0, "
                "releases naming an assign 28 (2 closed a live job, 26 named a job already closed)") in out, out
        assert census_mod.main(["--fixture", str(FIXTURE), "--since", "2026-10-17"]) == 0
        assert "re-assigned after a close 1 (packs: TP-702), releases naming an assign 0" in capsys.readouterr().out

    def test_the_new_job_after_the_claim_rule_closed_one_is_counted(self):
        """TP-702 on 10-17: closed by the seat's claim and re-sent at once for
        its next wave, so the re-send is a new job. Dies to: a re-send after a
        close read as a re-send of a live job."""
        data = census_mod.census(census_mod.read_fixture(FIXTURE), DAY.replace(day=17), NEXT)
        sends = data["dispatcher_sends"]["2026-10-17"]
        assert sends["assigns_sent"] == sends["jobs_given"] == 21

    def test_jobs_ends_the_window_where_the_next_new_job_was_given(self, capsys):
        """TP-703's line 6 is counted in new jobs from a merge's stamp. Dies to:
        the window ended at the Nth job (cutting its own releases short) or at
        the next assign of any kind, or a short window passed off as whole."""
        assert census_mod.main(["--fixture", str(FIXTURE), "--since", "2026-10-18", "--jobs", "10", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["until"] == "2026-10-18T09:32:14Z" and len(data["new_jobs"]) == 10
        assert data["totals"]["jobs_given"] == 10 and data["totals"]["hand_releases_of_closed_jobs"] == 11
        assert "so it holds 10 new jobs" in data["jobs_window"]
        assert census_mod.main(["--fixture", str(FIXTURE), "--since", "2026-10-18", "--jobs", "30"]) == 0
        assert "only 25 new jobs since 2026-10-18T00:00:00Z" in capsys.readouterr().out
        for bad in (["--jobs", "10"], ["--since", "2026-10-18", "--jobs", "0"],
                    ["--since", "2026-10-18", "--until", "2026-10-19", "--jobs", "10"]):
            assert census_mod.main(["--fixture", str(FIXTURE), *bad]) == 2, bad
        assert "--jobs N (N of 1 or more) ends a window that --since opens" in capsys.readouterr().err

    def test_as_row_needs_a_seat_and_a_date(self, capsys):
        """Dies to: a row printed for every seat, or for today, when one is asked."""
        assert census_mod.main(["--fixture", str(FIXTURE), "--as-row", "--seat", "win"]) == 2
        assert "--as-row needs --seat and --date" in capsys.readouterr().err

    def test_every_hand_release_is_counted_whatever_the_fold_closed_first(self):
        """The pre-registered measure: the releases naming an assign, each a
        hand's work, on the row of whoever sent them. The fold records only a
        job's first closer, so a hand release of a job the third rule already
        closed shows here and nowhere else. Dies to: the count read from the
        fold's record (2, not 28)."""
        data = census_mod.census(census_mod.read_fixture(FIXTURE), DAY, NEXT)
        assert data["dispatcher_sends"] == {"2026-10-18": {
            "assigns_sent": 25, "jobs_given": 25, "requests_answered": 23}}
        assert {r["seat"]: (r["hand_releases"], r["hand_releases_closing"]) for r in data["rows"]} == {
            "air": (28, 2), "air-work": (0, 0), "win": (0, 0), "win-2": (0, 0)}

    def test_the_dispatchers_row_is_what_it_sent(self, capsys):
        """TP-703d files the dispatcher's day from this row. Dies to: the
        dispatcher's row printed as a receiving seat's (all zeros on a day it
        sent 25 assigns)."""
        assert census_mod.main(["--fixture", str(FIXTURE), "--seat", "air", "--date", "2026-10-18", "--as-row"]) == 0
        out = capsys.readouterr().out
        assert ("assigns sent 25 (25 new jobs); releases naming an assign 28 (2 closed a live job, 26 named a "
                "job already closed); the day's worker requests it answered 23;") in out
        assert "assigns received" not in out
        # The releases it owes: the jobs live at the day's end, per seat (TP-703d
        # Task 0 item 6 found the row lacked it while the JSON carried it).
        assert "jobs live at 2026-10-19T00:00:00Z 2 (win 1, win-2 1)" in out, out

    def test_a_pack_re_sent_after_a_wave_closed_it_is_counted_under_its_id(self):
        """TP-702 was assigned by its id; a wave's push closed it by the claim
        rule on 2026-10-17 and the dispatcher re-sent it for the next wave.
        Dies to: the re-assign column missing, or the job's name left off."""
        data = census_mod.census(census_mod.read_fixture(FIXTURE), DAY.replace(day=17), DAY)
        assert [(r["seat"], r["reassigned_packs"], r["reassigned_rows"]) for r in data["rows"]
                if r["reassigned_after_close"]] == [("air-work", ["TP-702"], [])]
        assert data["totals"]["reassigned_after_close"] == 1


class TestTheCensusReadsTheRulesFromTheFold:
    """The closing rules have one home, ``tools/cc/mail.py::live_assignments``;
    the census counts closures from the record the fold keeps."""

    def test_a_closure_is_counted_from_the_folds_own_record(self, monkeypatch):
        """Dies to: the census re-stating the rules (it would count this
        closure as ``claim``, whatever the fold said)."""
        real = census_mod._mail()

        class Relabelled:
            def __getattr__(self, name):
                return getattr(real, name)

            @staticmethod
            def live_assignments(by_machine, dispatcher=None, *, closed=None):
                mine: list = []
                live = real.live_assignments(by_machine, dispatcher, closed=mine)
                if closed is not None:
                    closed.extend((a, r, "ack") for a, r, _rule in mine)
                return live

        monkeypatch.setattr(census_mod, "_mail", Relabelled)
        src = _src(_m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", ids=["DEF-1"]),
                   _m("win", "claim", "2026-10-18T02:00:00Z", "c1", lane="lane/y", ids=["DEF-1"]),
                   _m("win", "release", "2026-10-18T03:00:00Z", "r1", lane="lane/y"))
        assert census_mod.census(src, DAY, NEXT)["totals"]["closed"] == {"claim": 0, "lane": 0, "ack": 1}

    def test_a_release_from_another_seat_closes_nothing(self):
        """Dies to: a release counted for the seat that sent it rather than the
        seat the job was given to."""
        src = _src(_m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", ids=["DEF-1"]),
                   _m("win", "claim", "2026-10-18T02:00:00Z", "c1", lane="lane/y", ids=["DEF-1"]),
                   _m("win-2", "release", "2026-10-18T03:00:00Z", "r1", lane="lane/y"))
        data = census_mod.census(src, DAY, NEXT)
        assert data["totals"]["closed"] == {"claim": 0, "lane": 0, "ack": 0}
        assert data["live"] == {"win": ["a1"]}

    def test_a_closure_counts_on_the_utc_day_of_its_release(self):
        """Dies to: a closure counted on its assign's day."""
        src = _src(_m("air", "assign", "2026-10-17T23:00:00Z", "a1", seat="win", ids=["DEF-1"]),
                   _m("win", "claim", "2026-10-17T23:30:00Z", "c1", lane="lane/y", ids=["DEF-1"]),
                   _m("win", "release", "2026-10-18T00:30:00Z", "r1", lane="lane/y"))
        data = census_mod.census(src, DAY, NEXT)
        assert [(r["seat"], r["day"], r["assigns_received"], r["closed"]["claim"]) for r in data["rows"]] == [
            ("win", "2026-10-18", 0, 1)]


class TestTheOtherColumns:
    """Merges, requests and words, each read from the source its docstring names."""

    def test_a_merged_branch_no_message_names_is_unattributed(self):
        """Dies to: an unnamed branch dropped silently, or given to a seat; or
        (DEF-4044) a branch no claim names but whose pull request carries the
        seat label the ship driver stamps left unattributed, or the label read
        over a claim."""
        src = _src(_m("win", "claim", "2026-10-18T01:00:00Z", "c1", lane="lane/y", ids=["DEF-1"]),
                   merged=[{"number": 7, "headRefName": "lane/y", "mergedAt": "2026-10-18T05:00:00Z"},
                           {"number": 8, "headRefName": "refresh-externals/x", "mergedAt": "2026-10-18T06:00:00Z"},
                           {"number": 9, "headRefName": "lane/u", "mergedAt": "2026-10-18T07:00:00Z",
                            "labels": [{"name": "seat:win"}]},
                           {"number": 10, "headRefName": "lane/y", "mergedAt": "2026-10-18T08:00:00Z",
                            "labels": [{"name": "seat:air"}]}])
        data = census_mod.census(src, DAY, NEXT)
        assert [(r["seat"], r["lanes_merged"]) for r in data["rows"]] == [("win", [7, 9, 10])]
        assert data["unattributed_merges"] == [8]

    def test_a_workers_request_is_counted_and_the_dispatchers_is_not(self):
        """The latency census's pairing leaves the dispatcher's own requests
        out. Dies to: the pairing replaced by a count of every request."""
        src = _src(_m("win", "request", "2026-10-18T01:00:00Z", "q1"),
                   _m("air", "ack", "2026-10-18T01:06:00Z", "k1", ack="q1"),
                   _m("air", "request", "2026-10-18T02:00:00Z", "q2"))
        rows = census_mod.census(src, DAY, NEXT)["rows"]
        assert [(r["seat"], r["requests"], r["answered"], r["median_minutes"]) for r in rows] == [
            ("win", 1, 1, 6.0)]

    def test_the_counted_words_are_read_from_a_text_or_a_fixture_flag(self):
        """START is a word anywhere in a text (the tier-run announcement); a
        marker is read where the text opens with it; a fixture carries either
        as a flag. Dies to: a word counted inside another word, or a fixture's
        flag ignored."""
        src = _src(_m("win", "note", "2026-10-18T01:00:00Z", "n1", text="START lane/y"),
                   _m("win", "note", "2026-10-18T02:00:00Z", "n2", text="RESTARTED the tier"),
                   _m("win", "note", "2026-10-18T03:00:00Z", "n3", shelved=True),
                   _m("win", "note", "2026-10-18T04:00:00Z", "n4", text="redirect: back to the census"),
                   _m("win", "ack", "2026-10-18T05:00:00Z", "k5", ack="q1", gridlock=True))
        r = census_mod.census(src, DAY, NEXT)["rows"][0]
        assert (r["start"], r["redirect"], r["shelved"], r.get("gridlock")) == (1, 1, 1, 1)
        assert r.get("gridlock_ids") == ["k5"]

    def test_the_census_reuses_the_latency_pairing_and_the_fragments_pattern(self):
        """The pairing and the Session Log name pattern have their homes; the
        census loads them by path. Dies to: a private copy that drifts."""
        assert census_mod._latency().pair.__module__ == "_sdc_latency"
        assert Path(census_mod._latency().__file__).name == "mail_latency_census.py"
        assert census_mod.session_log_names(["2026-10-18-174440-air-work.md", "README.md"]) == [
            ("2026-10-18", "air-work")]

    def test_only_the_first_assign_after_a_close_counts_and_on_its_own_day(self):
        """Dies to: an out-of-window re-send skipped and a later re-send of the
        live job counted in its place."""
        src = _src(_m("air", "assign", "2026-10-17T01:00:00Z", "a1", seat="win", ids=["DEF-1"]),
                   _m("win", "claim", "2026-10-17T02:00:00Z", "c1", lane="lane/y", ids=["DEF-1"]),
                   _m("win", "release", "2026-10-17T03:00:00Z", "r1", lane="lane/y"),
                   _m("air", "assign", "2026-10-17T04:00:00Z", "a2", seat="win", ids=["DEF-1"]),
                   _m("air", "assign", "2026-10-18T05:00:00Z", "a3", seat="win", ids=["DEF-1"]))
        assert census_mod.census(src, DAY, NEXT)["totals"]["reassigned_after_close"] == 0
        wider = census_mod.census(src, DAY.replace(day=17), NEXT)
        assert [(r["day"], r["reassigned_rows"]) for r in wider["rows"] if r["reassigned_after_close"]] == [
            ("2026-10-17", ["DEF-1"])]

    def test_a_job_closed_by_hand_or_by_its_lane_and_re_sent_is_not_counted(self):
        """The column is the strike rule's trigger: the third rule closed a job
        whose work was not done. A job the dispatcher released by hand, or
        whose own lane shipped, and then re-sent is the dispatcher's own call.
        Dies to: every rule's closure followed for a re-assign."""
        src = _src(_m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", ids=["DEF-1"]),
                   _m("air", "release", "2026-10-18T02:00:00Z", "r1", ack="a1"),
                   _m("air", "assign", "2026-10-18T03:00:00Z", "a2", seat="win", ids=["DEF-1"]),
                   _m("air", "assign", "2026-10-18T01:00:00Z", "b1", seat="win", lane="lane/b"),
                   _m("win", "release", "2026-10-18T02:00:00Z", "r2", lane="lane/b"),
                   _m("air", "assign", "2026-10-18T03:00:00Z", "b2", seat="win", lane="lane/b"))
        data = census_mod.census(src, DAY, NEXT)
        assert data["totals"]["closed"] == {"claim": 0, "lane": 1, "ack": 1}
        assert data["totals"]["reassigned_after_close"] == 0

    def test_a_workers_assign_is_not_counted_where_a_dispatcher_is_named(self):
        """Dies to: the dispatcher filter dropped from the assigns the census counts."""
        src = _src(_m("win-2", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", ids=["DEF-1"]))
        data = census_mod.census(src, DAY, NEXT)
        assert data["totals"]["assigns_received"] == 0 and data["live"] == {}

    def test_a_message_stamped_at_the_end_of_the_window_is_not_read(self):
        """A release, a note or a merge at ``until`` exactly is the next
        window's, and a lane first named after the window names no seat in it.
        Dies to: the fold or the lane reading past the window's end, or either
        bound made inclusive."""
        src = _src(_m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", ids=["DEF-1"]),
                   _m("win", "claim", "2026-10-18T02:00:00Z", "c1", lane="lane/y", ids=["DEF-1"]),
                   _m("win", "release", "2026-10-19T00:00:00Z", "r1", lane="lane/y"),
                   _m("win", "note", "2026-10-19T00:00:00Z", "n1", text="START lane/z"),
                   _m("win", "claim", "2026-10-19T01:00:00Z", "c2", lane="lane/q"),
                   merged=[{"number": 8, "headRefName": "lane/y", "mergedAt": "2026-10-19T00:00:00Z"},
                           {"number": 9, "headRefName": "lane/q", "mergedAt": "2026-10-18T05:00:00Z"}])
        data = census_mod.census(src, DAY, NEXT)
        assert data["live"] == {"win": ["a1"]} and data["totals"]["closed"]["claim"] == 0
        assert data["totals"]["start"] == 0
        assert data["totals"]["lanes_merged"] == 0 and data["unattributed_merges"] == [9]

    def test_a_session_log_name_outside_the_window_is_not_counted(self):
        """Dies to: the Session Log names counted without their day."""
        src = _src(session_log=["2026-10-17-235900-win.md", "2026-10-18-120000-win.md",
                                "2026-10-19-000100-win.md"])
        assert [(r["seat"], r["day"], r["session_log_rows"]) for r in census_mod.census(src, DAY, NEXT)["rows"]] == [
            ("win", "2026-10-18", 1)]

    def test_a_marker_counts_where_a_text_opens_with_it_and_a_quotation_mid_text_does_not(self):
        """``redirect:``, ``shelved:`` and ``gridlock:`` are the words a seat
        opens a message with when it moves off a job or rules a gridlock; the
        briefs and the assigns quote the same words mid-text (8 of 9
        ``redirect:`` and 5 of 5 ``shelved:`` mentions on the refs by
        2026-10-30 were such quotations, DEF-5029). The text is read as the
        driver stores it, stripped on send, so a leading space is no opening
        (the operator-call rule reads the same way), and ``gridlock:`` counts
        on the dispatcher's ack or note alone. Dies to: the colon dropped (prose about
        a redirect counted), the marker searched anywhere in the text (a
        quotation counted), a leading space let through, or a worker's ack
        counted as a ruling."""
        src = _src(_m("win", "note", "2026-10-18T01:00:00Z", "n1", text="redirect to the census"),
                   _m("win", "note", "2026-10-18T02:00:00Z", "n2", text="shelved the idea for now"),
                   _m("win", "note", "2026-10-18T03:00:00Z", "n3", text="redirect: lane/z first"),
                   _m("win", "request", "2026-10-18T04:00:00Z", "q4",
                      text="an ack beginning redirect: re-aims; one note beginning shelved: says what was tried; "
                           "a gridlock: marker on the ruling ack"),
                   _m("win", "note", "2026-10-18T05:00:00Z", "n5", text="shelved: the tier reds twice on test_x"),
                   _m("win", "ack", "2026-10-18T06:00:00Z", "k6", ack="q4", text="gridlock: a worker's ack is no ruling"),
                   _m("win", "note", "2026-10-18T07:00:00Z", "n7", text="  redirect: a leading space is no opening"),
                   _m("air", "ack", "2026-10-18T08:00:00Z", "k8", ack="q4", text="gridlock: ruling on q4, the facts read"))
        rows = {r["seat"]: (r["redirect"], r["shelved"], r.get("gridlock")) for r in census_mod.census(src, DAY, NEXT)["rows"]}
        assert rows == {"win": (1, 1, 0), "air": (0, 0, 1)}
        assert census_mod.MARKERS == {"redirect": "redirect:", "shelved": "shelved:", "gridlock": "gridlock:",
                                      "stopped": "stopped:"}

    def test_a_stop_counts_on_a_request_alone_where_its_text_opens_with_the_marker(self):
        """DEF-5030 (2026-10-30): a worker's stop is a request opening with
        ``stopped:`` (``tools/cc/mail.py::STOPPED_PREFIX``; the board's asks
        line counts it apart), counted on the sender's row on a request alone,
        as the operator call is read: a note, an ack or an assign opening with
        the word, or a quotation mid-text, is no stop, and a leading space is
        no opening. Dies to: the word read on a note, read anywhere in a text,
        or left out of the row's text form."""
        src = _src(_m("win", "request", "2026-10-18T01:00:00Z", "q1", text="stopped: a conflict outside my files"),
                   _m("win", "note", "2026-10-18T02:00:00Z", "n2", text="stopped: a note is no stop"),
                   _m("air", "ack", "2026-10-18T03:00:00Z", "k3", ack="q1", text="stopped: an ack is no stop either"),
                   _m("air", "assign", "2026-10-18T04:00:00Z", "a4", seat="win-2",
                      text="a request opening with stopped: is a stop"),
                   _m("win-2", "request", "2026-10-18T05:00:00Z", "q5", text="  stopped: a leading space is no opening"))
        data = census_mod.census(src, DAY, NEXT)
        rows = {r["seat"]: r["stopped"] for r in data["rows"]}
        assert rows["win"] == 1 and not any(v for s, v in rows.items() if s != "win"), rows
        assert data["totals"]["stopped"] == 1
        assert "gridlock: 0, stopped: 1." in census_mod.as_row(data, "win", "2026-10-18")
        assert "gridlock: 0, stopped: 0." in census_mod.as_row(data, "win-2", "2026-10-18")

    def test_a_gridlock_ruling_counts_on_its_senders_row_and_the_row_names_each_rulings_id(self):
        """The ruling opens with ``gridlock:`` (the dispatcher brief's
        sentence, tools/cc/seat.py::SELF_HOST_GRIDLOCK): an ack, or a note
        where no request waits on the ruling (DEF-4060: air-work sat held
        07:25Z to 10:58Z on 2026-10-31 with no request open, and the ruling,
        note 20261031T105813Z-air-c80653, was the first of the day's three and
        the one the row left out). So the day row the handoff derives names
        the rulings the operator can reverse (the protocol's falsifier: two
        reversals in a week re-open the rule). Only the dispatcher's acks and
        notes count, as only a request is an operator call: a note and an ack
        from each sender, and the dispatcher's own quotation mid-text, which
        only the opening test now keeps out. Dies to: the count kept without
        the ids, the ids printed on a row with none or out of time order, a
        ruling counted on the row of the seat it answered, the dispatcher's
        note left out, its quotation counted, a worker's request, ack or note
        counted, or the text form leaving the word out."""
        src = _src(_m("win", "request", "2026-10-18T01:00:00Z", "q1",
                      text="gridlock: lane/x and lane/y both edit board.py; which first?"),
                   _m("air", "ack", "2026-10-18T02:00:00Z", "k1", ack="q1", text="gridlock: win first, the facts read"),
                   _m("air", "ack", "2026-10-18T01:30:00Z", "k2", ack="q1", text="gridlock: and win-2 catches up"),
                   _m("air", "note", "2026-10-18T02:30:00Z", "n4",
                      text="gridlock: win-2's window re-armed, no request names it, the facts read"),
                   _m("win", "ack", "2026-10-18T02:40:00Z", "k5", ack="n4", text="gridlock: a worker's ack is no ruling"),
                   _m("win", "note", "2026-10-18T02:50:00Z", "n5", text="gridlock: a worker's note is no ruling"),
                   _m("win-2", "note", "2026-10-18T03:00:00Z", "n3", text="read k1, a gridlock: ruling, catching up"),
                   _m("air", "note", "2026-10-18T03:10:00Z", "n6", text="read k1, a gridlock: ruling, no change"))
        data = census_mod.census(src, DAY, NEXT)
        rows = {r["seat"]: (r["gridlock"], r["gridlock_ids"]) for r in data["rows"]}
        # The worker's request opening with the word is a question, not a ruling, and its
        # ack and note rule nothing; win-2's quotation opens no row of its own and air's
        # adds none to air's; the ids read in time order, not in the order the ref lists them.
        assert rows == {"air": (3, ["k2", "k1", "n4"]), "win": (0, [])}
        assert data["totals"]["gridlock"] == 3
        air_row = census_mod.as_row(data, "air", "2026-10-18")
        assert "shelved: 0, gridlock: 3 (k2, k1, n4), stopped: 0." in air_row, air_row
        for seat in ("win", "win-2"):
            row = census_mod.as_row(data, seat, "2026-10-18")
            assert "shelved: 0, gridlock: 0, stopped: 0." in row and "(" not in row.split("gridlock:")[1], row
        text = census_mod.render(data, {})
        assert "2026-10-18 air: merged 0, " in text and "shelved: 0, gridlock: 3 (k2, k1, n4), stopped: 0\n" in text, text
        assert "2026-10-18 win: merged 0, " in text and "shelved: 0, gridlock: 0, stopped: 0\n" in text, text
        assert "2026-10-18 win-2:" not in text, text

    def test_a_gridlock_ruling_rides_an_ack_or_a_note_and_no_other_kind(self):
        """DEF-4060: the kinds a ruling rides, read on one message each. With a
        dispatcher named, its ack and its note opening with ``gridlock:`` are
        rulings and its request, assign, release and claim are not (a request
        is a question, an assign a job, a release or a claim a lane's
        bookkeeping); a worker's ack or note is none. With none named, every
        seat's ack and note count, as every seat's assigns do. The marker is
        the first word, so a note opening with the seat it is for is no ruling
        (37 of the dispatcher's 46 notes from 2026-10-25 to 10-31 opened with
        a seat's name, so the brief puts the name after the marker). Dies to:
        the note left out, the kind test dropped or widened (a request, an
        assign or a claim counted), the sender test dropped, or the marker read
        past an address."""
        def ruling(kind: str, sender: str, dispatcher: str | None = "air", text: str = "gridlock: x") -> bool:
            return census_mod._words({"type": kind, "from": sender, "text": text}, dispatcher)["gridlock"]

        assert (ruling("ack", "air"), ruling("note", "air")) == (True, True)
        assert (ruling("request", "air"), ruling("assign", "air"), ruling("release", "air"),
                ruling("claim", "air")) == (False, False, False, False)
        assert (ruling("ack", "win"), ruling("note", "win")) == (False, False)
        assert (ruling("ack", "win", None), ruling("note", "win", None), ruling("request", "win", None)) == (
            True, True, False)
        assert ruling("note", "air", text="air-work, gridlock: your marker re-armed") is False
        assert ruling("note", "air", text="gridlock: air-work, your marker re-armed") is True

    def test_each_senders_releases_naming_an_assign_count_on_its_row_split_by_whether_each_closed_a_job(self):
        """A seat may release its own job by hand too; the measure counts every
        sender's. Dies to: a seat's release counted on the dispatcher's row, or
        a release of a job already closed counted as closing it."""
        src = _src(_m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", ids=["DEF-1"]),
                   _m("air", "assign", "2026-10-18T01:00:00Z", "a2", seat="win", ids=["DEF-2"]),
                   _m("win", "claim", "2026-10-18T02:00:00Z", "c1", lane="lane/y", ids=["DEF-1"]),
                   _m("win", "release", "2026-10-18T03:00:00Z", "r1", lane="lane/y"),
                   _m("air", "release", "2026-10-18T04:00:00Z", "r2", ack="a1"),
                   _m("air", "release", "2026-10-18T04:00:00Z", "r3", ack="a2"),
                   _m("win", "release", "2026-10-18T05:00:00Z", "r4", ack="a2"),
                   _m("air", "assign", "2026-10-18T01:00:00Z", "a3", seat="win", ids=["DEF-3"]),
                   _m("win", "release", "2026-10-18T05:00:00Z", "r5", ack="a3"))
        rows = {r["seat"]: (r["hand_releases"], r["hand_releases_closing"])
                for r in census_mod.census(src, DAY, NEXT)["rows"]}
        assert (rows["air"], rows["win"]) == ((2, 1), (2, 1))


    def test_a_re_send_of_a_live_job_is_not_new_and_the_one_after_a_close_is(self):
        """The measure's window counts jobs, not assigns. Asymmetric on purpose:
        the right count (2 of 4) differs from the one an inverted comparison of
        the close and the assign gives (3 of 4). Dies to: every assign counted
        as a new job, or the close read as later than the assign after it."""
        src = _src(_m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", ids=["DEF-1"]),
                   _m("air", "assign", "2026-10-18T02:00:00Z", "a2", seat="win", ids=["DEF-1"]),
                   _m("air", "assign", "2026-10-18T03:00:00Z", "a3", seat="win", ids=["DEF-1"]),
                   _m("air", "release", "2026-10-18T04:00:00Z", "r1", ack="a3"),
                   _m("air", "assign", "2026-10-18T05:00:00Z", "a4", seat="win", ids=["DEF-1"]))
        data = census_mod.census(src, DAY, NEXT)
        sends = data["dispatcher_sends"]["2026-10-18"]
        assert (sends["assigns_sent"], sends["jobs_given"]) == (4, 2)
        assert data["new_jobs"] == ["2026-10-18T01:00:00Z", "2026-10-18T05:00:00Z"]

    def test_a_release_naming_a_claim_is_not_a_release_of_a_job(self):
        """The dispatcher also releases claims by id (three times on 2026-10-15).
        Dies to: every release with an ``ack`` counted as one naming an assign."""
        src = _src(_m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", ids=["DEF-1"]),
                   _m("win", "claim", "2026-10-18T02:00:00Z", "c1", lane="lane/y", ids=["DEF-1"]),
                   _m("air", "release", "2026-10-18T03:00:00Z", "r1", ack="c1"))
        rows = {r["seat"]: r for r in census_mod.census(src, DAY, NEXT)["rows"]}
        assert "air" not in rows or (rows["air"]["hand_releases"], rows["air"]["hand_releases_closing"]) == (0, 0)

    def test_a_request_a_peer_answered_is_not_the_dispatchers(self):
        """Dies to: the dispatcher credited with every answered worker request."""
        src = _src(_m("win", "request", "2026-10-18T01:00:00Z", "q1"),
                   _m("win-2", "ack", "2026-10-18T01:05:00Z", "k1", ack="q1"),
                   _m("win-2", "request", "2026-10-18T02:00:00Z", "q2"),
                   _m("air", "ack", "2026-10-18T02:05:00Z", "k2", ack="q2"))
        assert census_mod.census(src, DAY, NEXT)["dispatcher_sends"]["2026-10-18"]["requests_answered"] == 1


    def test_a_seats_own_row_prints_its_releases_naming_an_assign(self):
        """TP-703d files the seat's row. Dies to: the seat row dropping the
        figure the dispatcher's row carries."""
        src = _src(_m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", ids=["DEF-1"]),
                   _m("win", "release", "2026-10-18T05:00:00Z", "r1", ack="a1"))
        row = census_mod.as_row(census_mod.census(src, DAY, NEXT), "win", "2026-10-18")
        assert "releases naming an assign 1 (1 closed a live job, 0 named a job already closed)" in row, row

    def test_a_job_naming_a_row_and_a_pack_is_a_row_and_the_text_names_both_kinds(self):
        """Dies to: every id a row's in place of any id, or the rows and the
        packs swapped in the text."""
        src = _src(_m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", ids=["DEF-2", "TP-9"]),
                   _m("win", "claim", "2026-10-18T02:00:00Z", "c1", lane="lane/y", ids=["DEF-2", "TP-9"]),
                   _m("win", "release", "2026-10-18T03:00:00Z", "r1", lane="lane/y"),
                   _m("air", "assign", "2026-10-18T04:00:00Z", "a2", seat="win", ids=["DEF-2", "TP-9"]),
                   _m("air", "assign", "2026-10-18T05:00:00Z", "b1", seat="win", ids=["TP-8"]),
                   _m("win", "claim", "2026-10-18T06:00:00Z", "c2", lane="lane/z", ids=["TP-8"]),
                   _m("win", "release", "2026-10-18T07:00:00Z", "r2", lane="lane/z"),
                   _m("air", "assign", "2026-10-18T08:00:00Z", "b2", seat="win", ids=["TP-8"]))
        data = census_mod.census(src, DAY, NEXT)
        row = next(r for r in data["rows"] if r["seat"] == "win")
        assert (row["reassigned_rows"], row["reassigned_packs"]) == (["DEF-2 TP-9"], ["TP-8"])
        assert " (rows: DEF-2 TP-9; packs: TP-8)" in census_mod.as_row(data, "win", "2026-10-18")

    def test_the_dispatchers_total_is_apart_from_every_senders(self):
        """Dies to: the dispatcher's own total counting every seat's releases."""
        src = _src(_m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", ids=["DEF-1"]),
                   _m("air", "assign", "2026-10-18T01:00:00Z", "a2", seat="win", ids=["DEF-2"]),
                   _m("air", "release", "2026-10-18T05:00:00Z", "r1", ack="a1"),
                   _m("win", "release", "2026-10-18T05:00:00Z", "r2", ack="a2"))
        t = census_mod.census(src, DAY, NEXT)["totals"]
        assert (t["hand_releases"], t["hand_releases_by_dispatcher"], t["hand_releases_of_closed_jobs"]) == (2, 1, 0)

    def test_the_dispatchers_sends_line_names_the_assigns_and_the_new_jobs_apart(self):
        """A re-send in the window makes the two counts differ. Dies to: the
        line printing one count twice."""
        src = _src(_m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", ids=["DEF-1"]),
                   _m("air", "assign", "2026-10-18T02:00:00Z", "a2", seat="win", ids=["DEF-1"]),
                   _m("air", "assign", "2026-10-18T03:00:00Z", "a3", seat="win", ids=["DEF-2"]))
        out = census_mod.render(census_mod.census(src, DAY, NEXT, NEXT), {})
        assert "2026-10-18 air sent: assigns 3 (2 new jobs), the day's worker requests it answered 0" in out, out
        assert "totals: assigns 3 (sent 3, 2 new jobs)" in out, out


class TestTheTicksASeatStoodUnderTwo:
    """DEF-5034: the census reported the jobs live at the window's end and
    nothing about how long a seat stood short of two, so the idle window the
    board's ``under two:`` line now shows (air-work, 03:27Z to 06:38Z on
    2026-10-30) was not measured. Per worker seat per UTC day: the ticks of
    the dispatcher's cadence (``tools/cc/seat.py::TICK_MINUTES``, sampled from
    00:00Z) at which the seat held fewer than two live jobs, from the fold's
    assigns, their re-sends and their closures."""

    @staticmethod
    def _cadence() -> int:
        """The dispatcher's loop interval, read from the brief's own line."""
        import re
        text = (REPO_ROOT / "tools" / "cc" / "seat.py").read_text(encoding="utf-8")
        return int(re.search(r'DISPATCHER_TICK = "/loop (\d+)m ', text).group(1))

    def test_the_ticks_are_counted_at_the_dispatchers_cadence_from_the_folds_assigns_and_closures(self):
        """The row's red. Dies to: a job's end read from anything but the
        fold's closure, the cadence typed in, or the dispatcher's seat counted."""
        src = _src(_m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", lane="lane/a"),
                   _m("air", "assign", "2026-10-18T02:00:00Z", "a2", seat="win", lane="lane/b"),
                   _m("win", "release", "2026-10-18T03:00:00Z", "r1", lane="lane/a"))
        data = census_mod.census(src, DAY, NEXT)
        assert "under_two" in data and "tick_minutes" in data, sorted(data)
        assert data["tick_minutes"] == self._cadence() == census_mod.dispatcher_tick_minutes()   # the default: seat.py's line
        data = census_mod.census(src, DAY, NEXT, tick_minutes=15)
        assert data["tick_minutes"] == 15
        per_hour = 4
        # win is present from the first assign naming it at 01:00, holds one job from
        # then and two from 02:00 to the lane release at 03:00: under two at every
        # present slot but that hour's.
        assert data["under_two"] == {"2026-10-18": {"win": {"under_two": 22 * per_hour, "ticks": 23 * per_hour}}}

    def test_a_re_send_keeps_the_job_one_and_a_re_send_to_another_seat_moves_it(self):
        """The fold's rule: the latest assign of a job wins, so a re-send is
        the same job (one, not two) and a re-send naming another seat moves
        it there; a release naming the assign closes it. Dies to: a re-send
        counted beside the first, the move left on the old seat, or the ack
        closure missed."""
        src = _src(_m("air", "assign", "2026-10-18T00:00:00Z", "a0", seat="win", lane="lane/c"),
                   _m("air", "assign", "2026-10-18T00:00:00Z", "a1", seat="win", lane="lane/a"),
                   _m("air", "assign", "2026-10-18T01:00:00Z", "a2", seat="win", lane="lane/b"),
                   _m("air", "assign", "2026-10-18T02:00:00Z", "a3", seat="win", lane="lane/b"),   # a re-send
                   _m("air", "release", "2026-10-18T03:00:00Z", "r1", ack="a1"),                  # lane/a closed
                   _m("air", "assign", "2026-10-18T04:00:00Z", "a4", seat="win-2", lane="lane/a"),  # new after the close
                   _m("air", "assign", "2026-10-18T05:00:00Z", "a5", seat="win-2", lane="lane/b"))  # lane/b moved
        data = census_mod.census(src, DAY, NEXT, tick_minutes=15)
        assert "under_two" in data, sorted(data)
        per_hour = 4
        # win: lane/c all day, lane/a to 03:00, lane/b from 01:00 to its move at 05:00 -> under two from 05:00 only.
        # win-2: present from 04:00 (lane/a), lane/b from 05:00 -> under two for that one hour of its 20.
        assert data["under_two"]["2026-10-18"] == {"win": {"under_two": 19 * per_hour, "ticks": 24 * per_hour},
                                                   "win-2": {"under_two": 1 * per_hour, "ticks": 20 * per_hour}}

    def test_a_day_so_far_counts_the_ticks_to_now_and_the_figure_prints_on_the_row_and_the_report(self):
        """Dies to: slots counted past now on a day not over, the figure left
        off the seat's row, the dispatcher's row (the one row a workflow writes
        from the census, so the workers' idle time lands on the record there)
        or the report."""
        src = _src(_m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", lane="lane/a"))
        data = census_mod.census(src, DAY, NEXT, now=DAY.replace(hour=6), tick_minutes=15)
        assert "under_two" in data, sorted(data)
        n = 5 * 4   # present from the assign at 01:00, counted to now at 06:00
        assert data["under_two"] == {"2026-10-18": {"win": {"under_two": n, "ticks": n}}}
        row = census_mod.as_row(data, "win", "2026-10-18")
        assert f"; under two at {n} of {n} tick slots;" in row, row
        own = census_mod.as_row(data, "air", "2026-10-18")
        assert f"; under two: win {n} of {n} tick slots;" in own, own
        text = census_mod.render(data, {})
        assert f"2026-10-18 under two (15-min tick slots from 00:00Z): win {n} of {n}" in text, text
        empty = census_mod.census(_src(), DAY, NEXT, tick_minutes=15)
        assert "under two: no worker seat present" in census_mod.as_row(empty, "air", "2026-10-18")

    def test_the_fixtures_ticks_under_two_on_10_18_are_pinned(self):
        """The frozen refs' figures (read 2026-10-30): a day of one-wave jobs
        closed at each push, so two of the three workers stood under two at
        nearly every tick; every seat first wrote on 10-17, so each is present
        all day. Dies to: the timeline's rules moved (a span's end, the
        presence rule, the dispatcher's seat) or the cadence sampled elsewhere."""
        data = census_mod.census(census_mod.read_fixture(FIXTURE), DAY, NEXT)
        assert "under_two" in data, sorted(data)
        # Pinned at 15 minutes outright (96 slots a day), so a changed loop
        # interval moves the default read's test, never these figures.
        data = census_mod.census(census_mod.read_fixture(FIXTURE), DAY, NEXT, tick_minutes=15)
        assert data["under_two"] == {"2026-10-18": {"air-work": {"under_two": 93, "ticks": 96},
                                                    "win": {"under_two": 53, "ticks": 96},
                                                    "win-2": {"under_two": 96, "ticks": 96}}}
        assert "air" not in data["under_two"]["2026-10-18"], "the dispatcher is given no job"

    def test_a_seat_silent_on_the_day_gets_its_ticks_and_no_row(self):
        """A seat the refs know and no message of the day names stood under
        two all day if it held no job; its figure is in the day's table and
        it gets no row of its own (the rows are the day's events). Dies to:
        the roster read from the day's rows, or a row made for the figure."""
        src = _src(_m("win-2", "note", "2026-10-17T01:00:00Z", "n1", text="x"),
                   _m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", lane="lane/a"))
        data = census_mod.census(src, DAY, NEXT, tick_minutes=15)
        assert "under_two" in data, sorted(data)
        per_hour = 4
        day = data["under_two"]["2026-10-18"]
        assert day == {"win": {"under_two": 23 * per_hour, "ticks": 23 * per_hour},
                       "win-2": {"under_two": 24 * per_hour, "ticks": 24 * per_hour}}
        assert [r["seat"] for r in data["rows"]] == ["win"]

    def test_a_seat_is_counted_from_its_first_stamp_while_within_the_quiet_horizon_or_holding_a_job(self):
        """The code review's case: a roster of every seat the refs ever named
        read a seat under two on days before it existed and after it retired.
        Dies to: a seat counted before its first stamp, a retired seat (no
        message in the board's quiet horizon, no live job) counted, or a dark
        seat holding a live job dropped."""
        import re
        text = (REPO_ROOT / "tools" / "cc" / "board.py").read_text(encoding="utf-8")
        assert census_mod.quiet_days() == int(re.search(r"^SEAT_QUIET_DAYS = (\d+)", text, re.M).group(1)) >= 2
        src = _src(_m("win-2", "note", "2026-10-18T05:00:00Z", "n1", text="x"),             # first seen at 05:00 on 10-18
                   _m("gone", "note", "2026-10-01T00:00:00Z", "n2", text="x"),               # retired: quiet, no job
                   _m("dark", "note", "2026-10-01T00:00:00Z", "n3", text="x"),               # quiet, but its job is live
                   _m("air", "assign", "2026-10-02T00:00:00Z", "a1", seat="dark", lane="lane/d"),
                   _m("air", "assign", "2026-10-17T01:00:00Z", "a2", seat="win", lane="lane/a"))
        data = census_mod.census(src, DAY.replace(day=16), NEXT, tick_minutes=15)
        assert "under_two" in data, sorted(data)
        per_hour = 4
        assert set(data["under_two"]["2026-10-16"]) == {"dark"}, data["under_two"]
        assert set(data["under_two"]["2026-10-17"]) == {"dark", "win"}, data["under_two"]
        assert data["under_two"]["2026-10-18"] == {"dark": {"under_two": 24 * per_hour, "ticks": 24 * per_hour},
                                                   "win": {"under_two": 24 * per_hour, "ticks": 24 * per_hour},
                                                   "win-2": {"under_two": 19 * per_hour, "ticks": 19 * per_hour}}

    def test_two_assigns_of_one_job_in_one_second_read_in_the_folds_order(self):
        """With no dispatcher named every machine's assigns count, and the fold
        orders two assigns of one job in one second by the sender's name, the
        later one winning. Dies to: the census ordering them by the stamp
        alone (a dict's order), so the span it ends and the span it keeps swap."""
        src = {"by_machine": {
                   "b": [_m("b", "assign", "2026-10-18T01:00:00Z", "b1", seat="win", lane="lane/x")],
                   "a": [_m("a", "assign", "2026-10-18T01:00:00Z", "a1", seat="win-2", lane="lane/x"),
                         _m("a", "assign", "2026-10-18T00:00:00Z", "a0", seat="win", lane="lane/y")]},
               "dispatcher": None, "merged": [], "session_log": []}
        data = census_mod.census(src, DAY, NEXT, tick_minutes=15)
        assert "under_two" in data, sorted(data)
        per_hour = 4
        assert data["live"] == {"win": ["a0", "b1"]}   # the fold keeps b's: the later sender
        day = data["under_two"]["2026-10-18"]
        # win holds lane/y and, from 01:00, lane/x; win-2's lane/x ended the second it was given;
        # the two senders are seats too here (no dispatcher stands apart), present from their first stamp.
        assert day["win"] == {"under_two": 1 * per_hour, "ticks": 24 * per_hour}
        assert day["win-2"] == {"under_two": 23 * per_hour, "ticks": 23 * per_hour}
        assert set(day) == {"a", "b", "win", "win-2"} and day["a"]["ticks"] == 24 * per_hour

    def test_a_closure_whose_stamp_does_not_read_drops_the_job_rather_than_keeping_it_live(self):
        """The fold pairs a release with its assign by the string order of the
        stamps; a stamp the parser refuses then has no place on the timeline.
        Dies to: the closed job read as live to the window's end (a fall-through
        to the next assign or to none)."""
        src = _src(_m("air", "assign", "2026-10-18T00:00:00Z", "a0", seat="win", lane="lane/c"),
                   _m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", lane="lane/a"),
                   _m("air", "release", "2026-10-18T03:00:00Q", "r1", ack="a1"))
        data = census_mod.census(src, DAY, NEXT, tick_minutes=15)
        assert "under_two" in data, sorted(data)
        per_hour = 4
        assert data["live"] == {"win": ["a0"]}, "the fold closed lane/a on the release, whatever its stamp reads"
        assert data["under_two"]["2026-10-18"]["win"] == {"under_two": 24 * per_hour, "ticks": 24 * per_hour}


def _stub_mail(monkeypatch, by_machine: dict, *, fetched=(True, ""), skipped=None, raises: str = ""):
    """``tools/cc/mail.py`` with its three reads of a clone faked: no git."""
    real = census_mod._mail()

    class Stub:
        def __getattr__(self, name):
            return getattr(real, name)

        @staticmethod
        def fetch_mail(root):
            return fetched

        @staticmethod
        def read_mail(root):
            if raises:
                raise real.Unresolvable(raises)
            return by_machine, dict(skipped or {})

        @staticmethod
        def dispatcher_setting(root):
            return "air", "the test's"

    monkeypatch.setattr(census_mod, "_mail", Stub)


class TestALiveReadSaysWhatItCouldNotRead:
    """``read_live`` and ``main`` with the clone's reads faked: a read that
    failed is said in every form of the output, never printed as a zero."""

    REFS = {"air": [_m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", ids=["DEF-1"])],
            "win": [_m("win", "claim", "2026-10-18T02:00:00Z", "c1", lane="lane/y", ids=["DEF-1"])],
            "win-2": [_m("win-2", "note", "2026-10-17T05:00:00Z", "n0", text="a day earlier")]}
    ARGS = ["--since", "2026-10-18", "--until", "2026-10-19"]

    def test_a_failed_fetch_and_a_failed_gh_read_are_said_in_the_json_and_the_row(self, tmp_path, monkeypatch, capsys):
        """Dies to: an unread merged list printed as ``lanes merged 0``, or a
        failed fetch dropped from the JSON and the row."""
        monkeypatch.chdir(tmp_path)
        _stub_mail(monkeypatch, self.REFS, fetched=(False, "origin unreachable"))
        seen = []

        def gh(argv, **kw):
            seen.append((argv, kw.get("cwd")))
            return subprocess.CompletedProcess(argv, 1, "", "gh: not logged in")

        monkeypatch.setattr(census_mod, "run_bounded", gh)
        assert census_mod.main(["--repo", str(tmp_path), *self.ARGS, "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["fetch"].startswith("failed (origin unreachable)")
        assert data["merged_note"] == "gh pr list failed: gh: not logged in"
        assert data["merged_read"] is False and data["totals"]["lanes_merged"] is None
        assert seen == [(["gh", "pr", "list", "--state", "merged", "--limit", str(census_mod.GH_LIMIT), "--json",
                          "number,headRefName,mergedAt,labels"], tmp_path.resolve())]
        assert census_mod.main(["--repo", str(tmp_path), "--seat", "win", "--date", "2026-10-18", "--as-row"]) == 0
        row = capsys.readouterr().out
        assert "mail failed (origin unreachable)" in row
        assert "lanes merged unread (gh pr list failed: gh: not logged in)" in row and "lanes merged 0" not in row
        assert census_mod.main(["--repo", str(tmp_path), "--seat", "win-2", "--date", "2026-10-18", "--as-row"]) == 0
        assert "lanes merged unread (gh pr list failed" in capsys.readouterr().out
        assert census_mod.main(["--repo", str(tmp_path), *self.ARGS]) == 0
        assert "fetch: failed (origin unreachable)" in capsys.readouterr().out

    def test_a_gh_read_that_times_out_is_a_note_never_a_crash(self, tmp_path, monkeypatch, capsys):
        """``run_bounded`` raises ``TimeoutExpired``, a ``SubprocessError``.
        Dies to: only ``OSError`` and ``ValueError`` caught at the gh read."""
        monkeypatch.chdir(tmp_path)
        _stub_mail(monkeypatch, self.REFS, skipped={"win": 2})

        def slow(argv, **kw):
            raise subprocess.TimeoutExpired(argv, 60)

        monkeypatch.setattr(census_mod, "run_bounded", slow)
        assert census_mod.main(["--repo", str(tmp_path), *self.ARGS]) == 0
        out = capsys.readouterr().out
        assert "merged pull requests: unread (gh pr list could not run:" in out
        assert "skipped 2 mail line(s) that do not parse" in out
        assert census_mod.main(["--repo", str(tmp_path), "--seat", "win", "--date", "2026-10-18", "--as-row"]) == 0
        assert "2 mail line(s) unread" in capsys.readouterr().out

    def test_refs_that_cannot_be_read_exit_2_with_the_reason(self, tmp_path, monkeypatch, capsys):
        """Dies to: the mail module's ``Unresolvable`` left uncaught (a
        traceback and exit 1, the code an unusable dispatcher setting owns)."""
        monkeypatch.chdir(tmp_path)
        _stub_mail(monkeypatch, {}, raises="git for-each-ref failed: not a git repository")
        assert census_mod.main(["--repo", str(tmp_path), "--no-fetch", *self.ARGS]) == 2
        assert "the mail refs cannot be read: git for-each-ref failed" in capsys.readouterr().err

    def test_a_list_at_its_limit_is_said(self):
        """Dies to: the limit read from anywhere but the argv that asks for it,
        or a full list printed as if it were all."""
        merged = [{"number": n, "headRefName": f"lane/{n}", "mergedAt": "2026-10-18T05:00:00Z"}
                  for n in range(census_mod.GH_LIMIT)]
        data = census_mod.census(_src(merged=merged), DAY, NEXT)
        assert data["merged_at_limit"] is True
        assert f"the list is at its limit ({census_mod.GH_LIMIT})" in census_mod.render(data, {})


class TestTheDayAndTheSeatAreRead:
    """``--date`` is one UTC day, a seat is one the refs name, and a day not
    over yet, or older than the Session Log the tree holds, says so."""

    def test_date_takes_a_calendar_day_alone(self, capsys):
        """Dies to: a stamp read as a day (a row labelled with the day holding
        a window from the stamp), or ``--date`` silently beating ``--since``."""
        assert census_mod.main(["--fixture", str(FIXTURE), "--date", "2026-10-18T13:00:00Z",
                                "--seat", "win", "--as-row"]) == 2
        assert "--date is a UTC day, YYYY-MM-DD" in capsys.readouterr().err
        assert census_mod.main(["--fixture", str(FIXTURE), "--date", "2026-10-18", "--since", "2026-10-17",
                                "--seat", "win", "--as-row"]) == 2
        assert "--date is one UTC day" in capsys.readouterr().err

    def test_a_seat_no_message_names_is_refused_and_seat_alone_is_refused(self, capsys):
        """Dies to: an all-zero row printed for a misspelt seat, or ``--seat``
        ignored without ``--as-row``."""
        assert census_mod.main(["--fixture", str(FIXTURE), "--seat", "wim", "--date", "2026-10-18", "--as-row"]) == 2
        assert "no message of the refs read names the seat 'wim'" in capsys.readouterr().err
        assert census_mod.main(["--fixture", str(FIXTURE), "--seat", "win", "--date", "2026-10-18"]) == 2
        assert "--seat names the row --as-row prints" in capsys.readouterr().err

    def test_a_day_not_over_yet_says_so_and_reads_the_live_jobs_now(self):
        """Dies to: today's row stamped with tomorrow's midnight as if the day
        were over."""
        src = _src(_m("air", "assign", "2026-10-18T01:00:00Z", "a1", seat="win", ids=["DEF-1"]))
        now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        data = census_mod.census(src, DAY, NEXT, now)
        assert data["so_far"] is True and data["live_at"] == "2026-10-18T12:00:00Z"
        row = census_mod.as_row(data, "win", "2026-10-18")
        assert "(seat-day census, UTC day; the day so far)" in row and "jobs live at 2026-10-18T12:00:00Z 1;" in row

    def test_the_archive_horizon_is_the_trees_oldest_name_even_outside_the_window(self):
        """Dies to: the horizon read from the window's own names (none here)."""
        src = _src(session_log=["2026-10-18-120000-win.md"])
        data = census_mod.census(src, DAY.replace(day=16), DAY.replace(day=17))
        assert data["session_log_oldest"] == "2026-10-18"
        assert "Session Log rows before 2026-10-18 are archived" in census_mod.as_row(data, "win", "2026-10-16")

    def test_a_day_older_than_the_session_log_the_tree_holds_says_so(self):
        """Fragments past the newest few are archived. Dies to: an archived
        day's rows printed as a plain zero."""
        src = _src(session_log=["2026-10-18-120000-win.md"])
        data = census_mod.census(src, DAY.replace(day=17), NEXT)
        assert data["session_log_oldest"] == "2026-10-18"
        assert "Session Log rows before 2026-10-18 are archived" in census_mod.as_row(data, "win", "2026-10-17")
        assert "archived" not in census_mod.as_row(data, "win", "2026-10-18")
