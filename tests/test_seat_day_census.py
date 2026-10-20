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
        """Dies to: an unnamed branch dropped silently, or given to a seat."""
        src = _src(_m("win", "claim", "2026-10-18T01:00:00Z", "c1", lane="lane/y", ids=["DEF-1"]),
                   merged=[{"number": 7, "headRefName": "lane/y", "mergedAt": "2026-10-18T05:00:00Z"},
                           {"number": 8, "headRefName": "refresh-externals/x", "mergedAt": "2026-10-18T06:00:00Z"}])
        data = census_mod.census(src, DAY, NEXT)
        assert [(r["seat"], r["lanes_merged"]) for r in data["rows"]] == [("win", [7])]
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
        """Dies to: a word counted inside another word, or a fixture's flag ignored."""
        src = _src(_m("win", "note", "2026-10-18T01:00:00Z", "n1", text="START lane/y"),
                   _m("win", "note", "2026-10-18T02:00:00Z", "n2", text="RESTARTED the tier"),
                   _m("win", "note", "2026-10-18T03:00:00Z", "n3", shelved=True),
                   _m("win", "note", "2026-10-18T04:00:00Z", "n4", text="redirect: back to the census"))
        r = census_mod.census(src, DAY, NEXT)["rows"][0]
        assert (r["start"], r["redirect"], r["shelved"]) == (1, 1, 1)

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

    def test_redirect_and_shelved_count_only_as_the_seats_write_them(self):
        """``redirect:`` and ``shelved:`` are the words a seat writes when it
        moves off a job. Dies to: the colon dropped (prose about a redirect
        counted)."""
        src = _src(_m("win", "note", "2026-10-18T01:00:00Z", "n1", text="redirect to the census"),
                   _m("win", "note", "2026-10-18T02:00:00Z", "n2", text="shelved the idea for now"),
                   _m("win", "note", "2026-10-18T03:00:00Z", "n3", text="redirect: lane/z first"))
        r = census_mod.census(src, DAY, NEXT)["rows"][0]
        assert (r["redirect"], r["shelved"]) == (1, 0)

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
                          "number,headRefName,mergedAt"], tmp_path.resolve())]
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
