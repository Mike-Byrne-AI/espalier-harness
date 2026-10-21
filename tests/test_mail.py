"""Contract tests for ``tools/cc/mail.py``: the asynchronous half of
cross-machine Claude -- one append-only ref per machine on origin.

Three layers, each with its own oracle:

* the pure parts (the message shape and its one schema, the line codec, the
  claims fold, the overlap test, the cursor) on synthetic messages;
* the orchestration of a send on a recording fake runner, for the refusals
  that must fire BEFORE any network call;
* REAL-GIT cases, because the ref mechanics are the thing under test: a bare
  origin with clones standing in for the machines, a send that lands on
  origin and touches nothing in the worktree, the other machine's fetch and
  read, a release closing a claim for every reader, the same-name refusal,
  a push origin refuses rolled back, and the CLI driven as a child once.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests._git_oracle import _git_env

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE = REPO_ROOT / "tools" / "cc" / "mail.py"
PY = sys.executable


def _load(path: Path, alias: str):
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mail():
    return _load(MODULE, "mail_under_test")


def _msg(mail, machine: str, type_: str, text: str = "hello", **kw) -> dict:
    return mail.new_message(machine, type_, text, **kw)


# ── the message and its schema ───────────────────────────────────────────────

class TestMessageShape:
    def test_the_writer_emits_exactly_the_pinned_keys_in_order(self, mail):
        m = _msg(mail, "mac", "note", "a note", lane="lane/x", paths=["tools/cc/x.py"])
        line = mail.encode(m)
        assert line.endswith("\n") and "\r" not in line and line.isascii()
        assert list(json.loads(line)) == list(mail.MESSAGE_KEYS)
        assert list(json.loads(line)["re"]) == list(mail.RE_KEYS)

    def test_a_reader_keys_on_a_subset_of_what_the_writer_emits(self, mail):
        """The parity the producer/consumer drift footgun asks for: the
        reader's required keys are the writer's, never a key of their own."""
        assert set(mail._REQUIRED_KEYS) < set(mail.MESSAGE_KEYS)
        m = _msg(mail, "mac", "note", "x")
        decoded, skipped = mail.decode_lines(mail.encode(m))
        assert skipped == 0 and decoded == [json.loads(mail.encode(m))]

    def test_a_line_that_is_not_a_message_is_skipped_and_counted(self, mail):
        good = mail.encode(_msg(mail, "mac", "note", "x"))
        text = "{not json\n" + good + '{"id": "a"}\n' + "\n" + '{"id":"b","type":"note","from":"mac","at":"t","re":[]}\n'
        decoded, skipped = mail.decode_lines(text)
        assert len(decoded) == 1 and skipped == 3

    def test_non_ascii_text_rides_escaped_and_comes_back_whole(self, mail):
        m = _msg(mail, "mac", "note", "caf\u00e9 \u2014 done")
        line = mail.encode(m)
        assert line.isascii()
        assert mail.decode_lines(line)[0][0]["text"] == "caf\u00e9 \u2014 done"

    def test_the_type_is_one_of_the_five(self, mail):
        with pytest.raises(mail.Unresolvable, match="one of claim, release, note, request, ack"):
            _msg(mail, "mac", "shout", "x")

    def test_a_claim_names_a_lane_a_class_or_a_path(self, mail):
        with pytest.raises(mail.Unresolvable, match="a claim names a lane"):
            _msg(mail, "mac", "claim", "")
        assert _msg(mail, "mac", "claim", "", lane="lane/x")["re"]["lane"] == "lane/x"
        assert _msg(mail, "mac", "claim", "", classes=["C13"])["re"]["classes"] == ["C13"]

    def test_a_release_or_ack_names_what_it_answers(self, mail):
        with pytest.raises(mail.Unresolvable, match="names the message it answers"):
            _msg(mail, "mac", "release", "")
        assert _msg(mail, "mac", "ack", "", ack="some-id")["ack"] == "some-id"
        assert _msg(mail, "mac", "release", "", lane="lane/x")["ack"] == ""

    def test_an_ack_names_the_message_it_answers_never_a_lane(self, mail):
        """A lane closes claims and jobs through a release; nothing reads a
        lane-only ack, so one was accepted and answered nothing, and the
        refusal text pointed at it (failure-mode review, TP-701 r1; 0 of 123
        acks on the live refs were lane-only, 2026-10-15). Dies to: a lane
        accepted in place of the id."""
        with pytest.raises(mail.Unresolvable, match=r"an ack names the message it answers \(--ack <id>\)"):
            _msg(mail, "mac", "ack", "done", lane="lane/x")
        with pytest.raises(mail.Unresolvable) as refused:
            _msg(mail, "mac", "ack", "done")
        assert "--lane" not in str(refused.value)

    def test_a_note_or_request_needs_text_and_the_text_is_capped(self, mail):
        with pytest.raises(mail.Unresolvable, match="needs text"):
            _msg(mail, "mac", "request", "   ")
        with pytest.raises(mail.Unresolvable, match="the cap is"):
            _msg(mail, "mac", "note", "x" * (mail.MAX_TEXT + 1))

    def test_paths_are_repo_relative_with_forward_slashes(self, mail):
        m = _msg(mail, "mac", "claim", "", paths=["tools\\cc\\x.py", "./docs/", "a/b/"])
        assert m["re"]["paths"] == ["tools/cc/x.py", "docs", "a/b"]
        for bad in ("/etc/x", "C:/x", "../up", "~/home"):
            with pytest.raises(mail.Unresolvable, match="repo-relative"):
                _msg(mail, "mac", "claim", "", paths=[bad])

    def test_the_machine_name_is_validated_at_the_message(self, mail):
        with pytest.raises(mail.Unresolvable, match="not a machine name"):
            _msg(mail, "Mac Book!", "note", "x")

    def test_the_stamp_and_id_are_utc_and_the_id_carries_the_machine(self, mail):
        now = datetime(2026, 10, 5, 12, 30, 0, tzinfo=timezone.utc)
        m = _msg(mail, "mac", "note", "x", now=now)
        assert m["at"] == "2026-10-05T12:30:00Z"
        assert m["id"].startswith("20261005T123000Z-mac-") and len(m["id"].rsplit("-", 1)[-1]) == 6

    def test_the_headline_is_one_ascii_line_with_who_what_and_the_first_words(self, mail):
        m = _msg(mail, "win", "request", "please look at the fixture hang \u2014 it recurs " + "x" * 100,
                 lane="lane/y", paths=["a.py", "b.py"])
        line = mail.headline(m)
        assert line.isascii() and "\n" not in line
        assert line.startswith('win: request re lane/y (2 paths) -- "please look at the fixture hang')
        assert line.endswith('..."') and len(line) < 130


# ── the fold and the overlap ─────────────────────────────────────────────────

class TestClaimsFold:
    def _claims(self, mail):
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        a = _msg(mail, "mac", "claim", "", lane="lane/a", paths=["tools/cc/"], now=now)
        b = _msg(mail, "mac", "claim", "", lane="lane/b", classes=["C13"], now=now)
        c = _msg(mail, "win", "claim", "", lane="lane/c", paths=["docs/x.md"], now=now)
        return a, b, c

    def test_a_release_naming_the_id_closes_that_claim_only(self, mail):
        a, b, c = self._claims(mail)
        release = _msg(mail, "mac", "release", "", ack=a["id"])
        live = mail.live_claims({"mac": [a, b, release], "win": [c]})
        assert {m["id"] for m in live} == {b["id"], c["id"]}

    def test_a_release_naming_a_lane_closes_every_claim_on_it_from_that_machine(self, mail):
        a, b, c = self._claims(mail)
        a2 = _msg(mail, "mac", "claim", "", lane="lane/a", paths=["docs/"])
        release = _msg(mail, "mac", "release", "", lane="lane/a")
        live = mail.live_claims({"mac": [a, a2, b, release], "win": [c]})
        assert {m["id"] for m in live} == {b["id"], c["id"]}

    def test_a_release_naming_a_foreign_id_closes_nothing(self, mail):
        a, b, c = self._claims(mail)
        release = _msg(mail, "win", "release", "", ack=a["id"])  # not win's claim
        live = mail.live_claims({"mac": [a], "win": [c, release]})
        assert {m["id"] for m in live} == {a["id"], c["id"]}

    def test_claims_come_back_oldest_first(self, mail):
        old = _msg(mail, "win", "claim", "", lane="old", now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        new = _msg(mail, "mac", "claim", "", lane="new", now=datetime(2026, 2, 1, tzinfo=timezone.utc))
        assert [m["id"] for m in mail.live_claims({"mac": [new], "win": [old]})] == [old["id"], new["id"]]

    def test_overlap_reads_a_directory_claim_either_way_plus_classes_and_the_lane(self, mail):
        a, b, c = self._claims(mail)
        found = mail.overlapping_claims([a, b, c], paths=["tools/cc/mail.py", "docs"], classes=["C13"],
                                        lane="lane/c", exclude_machine=None)
        by_id = {claim["id"]: hits for claim, hits in found}
        assert by_id[a["id"]] == ["path tools/cc/mail.py (their tools/cc)"]
        assert by_id[b["id"]] == ["class C13"]
        assert by_id[c["id"]] == ["path docs (their docs/x.md)", "lane lane/c"]

    def test_overlap_skips_this_machines_own_claims(self, mail):
        a, b, c = self._claims(mail)
        found = mail.overlapping_claims([a, b, c], paths=["tools/cc/mail.py"], exclude_machine="mac")
        assert found == []

    def test_claims_minted_in_one_second_keep_a_total_order(self, mail):
        """The fold's order is the stamp, the machine, then the position in
        the machine's file -- never the id's random tail, which put two claims
        minted in one second in either order on alternate runs (failure-mode
        review, 2026-10-05: 11 of 20 runs red)."""
        now = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)
        mac_a = _msg(mail, "mac", "claim", "", lane="a", now=now)
        mac_b = _msg(mail, "mac", "claim", "", lane="b", now=now)
        win_c = _msg(mail, "win", "claim", "", lane="c", now=now)
        for _ in range(20):
            live = mail.live_claims({"win": [win_c], "mac": [mac_a, mac_b]})
            assert [m["id"] for m in live] == [mac_a["id"], mac_b["id"], win_c["id"]]

    def test_overlap_skips_a_token_it_cannot_read_and_keeps_the_rest(self, mail):
        """One bad path in a plan's step text costs itself, never the warnings
        for the rest: before this, `files: ~/notes.md` raised and the whole
        pre-flight fell silent (failure-mode review, 2026-10-05)."""
        a, b, c = self._claims(mail)
        found = mail.overlapping_claims([a, b, c], paths=["~/notes.md", "C:/x", "../up", "tools/cc/mail.py"])
        assert [claim["id"] for claim, _hits in found] == [a["id"]]


class TestAssignments:
    """TP-479 Wave A-3 (layer L4): the dispatcher assigns JOBS (a pack, a
    wave, a ledger class) to seats with an ``assign`` message, so seats stop
    negotiating with each other. Path areas were refuted (47 of 65
    code-touching pull requests crossed a three-way split), so the job is the
    unit; files keep their claims."""

    _T0 = datetime(2026, 10, 9, 20, 0, 0, tzinfo=timezone.utc)
    _T1 = datetime(2026, 10, 9, 21, 0, 0, tzinfo=timezone.utc)

    def test_an_assign_names_a_seat_and_a_job(self, mail):
        """Dies to: an assign accepted with no seat, a bad seat or no job."""
        m = _msg(mail, "air", "assign", "", seat="win", lane="TP-479 wave B", ids=["TP-479"])
        assert m["re"]["seat"] == "win"
        assert m["re"]["lane"] == "TP-479 wave B"
        for kw in ({"lane": "TP-479 wave B"}, {"seat": "Not A Seat", "lane": "x"}, {"seat": "win"}):
            with pytest.raises(mail.Unresolvable):
                _msg(mail, "air", "assign", "", **kw)
        with pytest.raises(mail.Unresolvable):
            _msg(mail, "air", "claim", "", lane="lane/x", seat="win")  # a seat belongs to an assign only

    def test_a_claim_keeps_its_exact_shape(self, mail):
        """Adding the assign type must not change a claim's encoding: an older
        reader on another box keeps reading every claim byte for byte."""
        claim = _msg(mail, "win", "claim", "", lane="lane/x", paths=["tools/cc/x.py"])
        assert list(claim["re"]) == ["lane", "classes", "paths", "ids"]

    def test_the_latest_assign_of_a_job_wins(self, mail):
        """Dies to: the first assign kept rather than the latest."""
        first = _msg(mail, "air", "assign", "", seat="win", lane="TP-479 wave B", now=self._T0)
        moved = _msg(mail, "air", "assign", "", seat="win-2", lane="TP-479 wave B", now=self._T1)
        other = _msg(mail, "air", "assign", "", seat="win", classes=["C13"], now=self._T0)
        live = mail.live_assignments({"air": [first, other, moved]})
        assert sorted((a["re"]["seat"], a["re"]["lane"] or a["re"]["classes"][0]) for a in live) == [
            ("win", "C13"), ("win-2", "TP-479 wave B")]

    def test_the_dispatcher_retracts_an_assign_by_its_id(self, mail):
        a = _msg(mail, "air", "assign", "", seat="win", lane="TP-479 wave B", now=self._T0)
        b = _msg(mail, "air", "assign", "", seat="win", classes=["C13"], now=self._T0)
        retract = _msg(mail, "air", "release", "", ack=a["id"], now=self._T1)
        assert [m["id"] for m in mail.live_assignments({"air": [a, b, retract]})] == [b["id"]]

    def test_only_the_dispatchers_assigns_count_when_one_is_named(self, mail):
        """Dies to: the dispatcher filter dropped (a worker assigning itself
        work would then read as the dispatcher's decision)."""
        theirs = _msg(mail, "air", "assign", "", seat="win", lane="job-a", now=self._T0)
        self_made = _msg(mail, "win-2", "assign", "", seat="win-2", lane="job-b", now=self._T0)
        by_machine = {"air": [theirs], "win-2": [self_made]}
        assert [m["id"] for m in mail.live_assignments(by_machine, dispatcher="air")] == [theirs["id"]]
        assert len(mail.live_assignments(by_machine)) == 2  # no dispatcher named: every seat's count

    def test_a_job_assigned_to_another_seat_is_an_overlap(self, mail):
        """The plan pre-flight's job arm. Dies to: this seat's own assignments
        reported as overlaps, or ids not compared."""
        mine = _msg(mail, "air", "assign", "", seat="win", ids=["TP-479"], now=self._T0)
        theirs = _msg(mail, "air", "assign", "", seat="win-2", ids=["TP-478"], classes=["C13"], now=self._T0)
        live = mail.live_assignments({"air": [mine, theirs]})
        found = mail.overlapping_assignments(live, ids=["TP-479", "TP-478"], classes=[], seat="win")
        assert [(a["id"], hits) for a, hits in found] == [(theirs["id"], ["id TP-478"])]
        assert mail.overlapping_assignments(live, classes=["C13"], seat="win")[0][1] == ["class C13"]
        assert mail.overlapping_assignments(live, ids=["TP-478"], seat="win-2") == []

    def test_the_dispatcher_is_read_from_the_tracked_config(self, mail, tmp_path):
        """A team setting, the same on every clone, so it is tracked (unlike
        the machine name). No key: every machine's assigns count. A key that is
        there but unusable fails CLOSED (the failure-mode review: `Air`, or a
        key under a table, let every worker assign itself work). Dies to: a key
        under a table read as the setting, or an unusable one read as unset."""
        assert mail.dispatcher_setting(tmp_path)[0] is None
        (tmp_path / "espalier.toml").write_text('handoff_push = true\n', encoding="utf-8")
        assert mail.dispatcher_setting(tmp_path)[0] is None
        (tmp_path / "espalier.toml").write_text('handoff_push = true\ndispatcher = "air"  # the Mac\n', encoding="utf-8")
        assert mail.dispatcher_setting(tmp_path)[0] == "air"
        for text, said in (('[other]\ndispatcher = "air"\n', "[other]"), ('dispatcher = "Air"\n', "Air"),
                           ('dispatcher = "Not A Seat"\n', "Not A Seat")):
            (tmp_path / "espalier.toml").write_text(text, encoding="utf-8")
            name, how = mail.dispatcher_setting(tmp_path)
            assert name == mail.DISPATCHER_UNUSABLE and said in how, text
        t = self._T0
        job = _msg(mail, "air", "assign", "", seat="win", lane="job-a", now=t)
        assert mail.live_assignments({"air": [job]}, mail.DISPATCHER_UNUSABLE) == []

    def test_a_job_closes_when_its_seat_or_its_assigner_releases_it(self, mail):
        """The failure-mode review's major: only the dispatcher's ack closed an
        assign, so every finished job warned forever (the claims defect of
        2026-10-05, again). The ship driver's lane release closes a job assigned
        by that lane; the seat's or the assigner's ack closes any. Dies to: the
        release read from the assigner only, or the lane not compared."""
        lane_job = _msg(mail, "air", "assign", "", seat="win", lane="lane/a", now=self._T0)
        id_job = _msg(mail, "air", "assign", "", seat="win", ids=["TP-479"], now=self._T0)
        other_job = _msg(mail, "air", "assign", "", seat="win-2", lane="lane/b", now=self._T0)
        seat_lane_release = _msg(mail, "win", "release", "", lane="lane/a", now=self._T1)
        seat_ack = _msg(mail, "win", "release", "", ack=id_job["id"], now=self._T1)
        bystander = _msg(mail, "win", "release", "", lane="lane/b", now=self._T1)   # not win's job
        live = mail.live_assignments({"air": [lane_job, id_job, other_job],
                                      "win": [seat_lane_release, seat_ack, bystander]}, dispatcher="air")
        assert [m["id"] for m in live] == [other_job["id"]]
        by_dispatcher = _msg(mail, "air", "release", "", lane="lane/b", now=self._T1)
        assert mail.live_assignments({"air": [other_job, by_dispatcher]}, dispatcher="air") == []

    def test_a_job_closes_when_its_seats_own_claim_on_the_shipped_lane_named_its_ids(self, mail):
        """An assign names row ids, the seat claims them on the lane it works,
        and the ship driver's lane release at the push closes the job: on
        2026-10-18, of the 22 jobs a hand closed, the seats' own claims had named
        every id of 21 before that hand release. Dies to: the claims never read,
        or the closure recorded under another rule."""
        job = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1", "DEF-2"], now=self._T0)
        claim = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-1", "DEF-2", "DEF-3"], now=self._T0)
        shipped = _msg(mail, "win", "release", "", lane="lane/y", now=self._T1)
        closed: list = []
        assert mail.live_assignments({"air": [job], "win": [claim, shipped]}, dispatcher="air", closed=closed) == []
        assert [(a["id"], r["id"], rule) for a, r, rule in closed] == [(job["id"], shipped["id"], "claim")]

    def test_only_the_seats_live_claims_on_the_released_lane_close_its_job(self, mail):
        """Each case is a mutation of the third rule, and each leaves the job
        live but one. Dies to: the seat test dropped, any shared id taken for
        every id, one claim read alone, a claim released by its id still
        counted, the assigner admitted, or any lane of the seat read."""
        job = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1", "DEF-2"], now=self._T0)

        def live(*by: tuple[str, list[dict]]) -> bool:
            machines: dict[str, list[dict]] = {"air": [job]}
            for who, msgs in by:
                machines.setdefault(who, []).extend(msgs)
            return [m["id"] for m in mail.live_assignments(machines, dispatcher="air")] == [job["id"]]

        claim = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-1", "DEF-2"], now=self._T0)
        short = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-1"], now=self._T0)
        other_half = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-2"], now=self._T0)
        elsewhere = _msg(mail, "win", "claim", "", lane="lane/z", ids=["DEF-1", "DEF-2"], now=self._T0)
        dropped = _msg(mail, "win", "release", "", ack=claim["id"], now=self._T0)
        ship_y = _msg(mail, "win", "release", "", lane="lane/y", now=self._T1)
        not_the_seat = _msg(mail, "win-2", "release", "", lane="lane/y", now=self._T1)
        the_assigner = _msg(mail, "air", "release", "", lane="lane/y", now=self._T1)
        assert live(("win", [claim]), ("win-2", [not_the_seat]))
        assert live(("win", [short, ship_y]))
        assert not live(("win", [short, other_half, ship_y]))
        assert live(("win", [claim, dropped, ship_y]))
        assert live(("win", [claim]), ("air", [the_assigner]))
        # The assigner's own claim on the lane, then its lane release: only the seat's claim closes the job.
        assigners_claim = _msg(mail, "air", "claim", "", lane="lane/y", ids=["DEF-1", "DEF-2"], now=self._T0)
        assert live(("air", [assigners_claim, the_assigner]))
        assert live(("win", [elsewhere, ship_y]))
        # The seat began the released lane too, with a claim that covers nothing of the job.
        unrelated_y = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-9"], now=self._T0)
        assert live(("win", [elsewhere, unrelated_y, ship_y]))

    def test_a_re_sent_assign_of_the_job_closes_with_its_seats_claim(self, mail):
        """The latest assign of a job wins, and the third rule closes the job.
        Dies to: the rule keyed on one assign's id."""
        first = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1"], now=self._T0)
        again = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1"], now=self._T0)
        claim = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-1"], now=self._T0)
        ship = _msg(mail, "win", "release", "", lane="lane/y", now=self._T1)
        assert mail.live_assignments({"air": [first, again], "win": [claim, ship]}, dispatcher="air") == []

    def test_the_closed_record_names_the_rule_that_closed_each_job(self, mail):
        """The seat-day census counts closures through this record, so the
        rules keep one home. Dies to: a closure recorded under another rule, or
        a record of a job that stayed live."""
        by_ack = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-9"], now=self._T0)
        by_lane = _msg(mail, "air", "assign", "", seat="win", lane="lane/a", now=self._T0)
        by_claim = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1"], now=self._T0)
        stays = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-7"], now=self._T0)
        claim = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-1"], now=self._T0)
        ack = _msg(mail, "air", "release", "", ack=by_ack["id"], now=self._T1)
        lanes = [_msg(mail, "win", "release", "", lane="lane/a", now=self._T1),
                 _msg(mail, "win", "release", "", lane="lane/y", now=self._T1)]
        closed: list = []
        live = mail.live_assignments({"air": [by_ack, by_lane, by_claim, stays, ack], "win": [claim, *lanes]},
                                     dispatcher="air", closed=closed)
        assert [m["id"] for m in live] == [stays["id"]]
        assert sorted((a["id"], rule) for a, _r, rule in closed) == sorted(
            [(by_ack["id"], "ack"), (by_lane["id"], "lane"), (by_claim["id"], "claim")])

    _T2 = datetime(2026, 10, 9, 22, 0, 0, tzinfo=timezone.utc)

    def test_a_claim_placed_before_the_job_was_given_does_not_close_it(self, mail):
        """A seat files a row on its current lane and claims its id there; the
        dispatcher then queues that row's fix as the seat's next job; the
        current lane's push must not close the queued job (DEF-2025's job on
        2026-10-18 closed three hours before the lane that fixed it shipped).
        Dies to: a claim counted whenever the fold read it."""
        early = _msg(mail, "win", "claim", "", lane="lane/now", ids=["DEF-1"], now=self._T0)
        job = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1"], now=self._T1)
        ship_now = _msg(mail, "win", "release", "", lane="lane/now", now=self._T2)
        live = mail.live_assignments({"air": [job], "win": [early, ship_now]}, dispatcher="air")
        assert [m["id"] for m in live] == [job["id"]]
        later = _msg(mail, "win", "claim", "", lane="lane/fix", ids=["DEF-1"], now=self._T1)
        ship_fix = _msg(mail, "win", "release", "", lane="lane/fix", now=self._T2)
        assert mail.live_assignments({"air": [job], "win": [later, ship_fix]}, dispatcher="air") == []

    def test_a_job_naming_no_ids_never_closes_by_a_claim(self, mail):
        """A lane-only or class-only job closes by its lane or its id, never by
        whatever lane its seat ships next. Dies to: the empty-ids guard dropped
        (every claim covers no ids at all)."""
        by_lane = _msg(mail, "air", "assign", "", seat="win", lane="lane/a", now=self._T0)
        by_class = _msg(mail, "air", "assign", "", seat="win", classes=["C13"], now=self._T0)
        claim = _msg(mail, "win", "claim", "", lane="lane/unrelated", ids=["DEF-9"], now=self._T1)
        ship = _msg(mail, "win", "release", "", lane="lane/unrelated", now=self._T2)
        live = mail.live_assignments({"air": [by_lane, by_class], "win": [claim, ship]}, dispatcher="air")
        assert sorted(m["id"] for m in live) == sorted([by_lane["id"], by_class["id"]])

    def test_only_the_releasing_seats_own_claims_count_and_only_its_own_are_released(self, mail):
        """Dies to: every sender's claims pooled into the cover, a lane release
        that releases another seat's claims of the same lane name, or the rule
        read on a release that names an id."""
        job = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1"], now=self._T0)
        theirs = _msg(mail, "win-2", "claim", "", lane="lane/y", ids=["DEF-1"], now=self._T1)
        ship = _msg(mail, "win", "release", "", lane="lane/y", now=self._T2)
        assert len(mail.live_assignments({"air": [job], "win-2": [theirs], "win": [ship]}, dispatcher="air")) == 1
        # The seat began the lane itself, after the job, with a claim that covers nothing of it.
        unrelated = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-9"], now=self._T1)
        assert len(mail.live_assignments({"air": [job], "win-2": [theirs], "win": [unrelated, ship]},
                                         dispatcher="air")) == 1
        mine = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-1"], now=self._T1)
        other_ship = _msg(mail, "win-2", "release", "", lane="lane/y", now=self._T1)
        assert mail.live_assignments({"air": [job], "win": [mine, ship], "win-2": [other_ship]},
                                     dispatcher="air") == []
        with_ack = _msg(mail, "win", "release", "", lane="lane/y", ack=mine["id"], now=self._T2)
        assert len(mail.live_assignments({"air": [job], "win": [mine, with_ack]}, dispatcher="air")) == 1

    def test_a_malformed_ids_field_costs_its_own_message_never_the_fold(self, mail):
        """Another seat's ref is text this reader did not write. Dies to: a
        claim's ids read without their shape checked (a TypeError in the board,
        the seat listing and the assignments verb), or a dict's keys read as ids."""
        job = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1"], now=self._T0)
        for bad in (5, True, 1.5, "DEF-1", {"DEF-1": 1}):
            claim = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-2"], now=self._T1)
            claim["re"]["ids"] = bad
            ship = _msg(mail, "win", "release", "", lane="lane/y", now=self._T2)
            live = mail.live_assignments({"air": [job], "win": [claim, ship]}, dispatcher="air")
            assert [m["id"] for m in live] == [job["id"]], bad

    def test_a_malformed_assign_field_costs_its_own_message_never_the_fold(self, mail):
        """The job key reads an assign's ``classes`` and ``ids``, text another
        seat wrote. Dies to: either read without its shape checked (a
        TypeError in the board, the banner's orders and the census)."""
        good = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1"], now=self._T0)
        claim = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-1"], now=self._T1)
        ship = _msg(mail, "win", "release", "", lane="lane/y", now=self._T2)
        for field in ("classes", "ids"):
            for bad in (5, True, 1.5):
                odd = _msg(mail, "air", "assign", "", seat="win-2", ids=["DEF-2"], now=self._T0)
                odd["re"][field] = bad
                live = mail.live_assignments({"air": [good, odd], "win": [claim, ship]}, dispatcher="air")
                assert [m["id"] for m in live] == [odd["id"]], (field, bad)

    def test_a_job_that_names_a_lane_closes_by_that_lane_never_by_a_claim_on_another(self, mail):
        """A job naming a lane is the lane rule's: the seat's claims on some
        other lane, shipped first, do not close it even when they name every
        id. Dies to: the claim rule read for a job that names a lane."""
        job = _msg(mail, "air", "assign", "", seat="win", lane="lane/a", ids=["DEF-1"], now=self._T0)
        claim = _msg(mail, "win", "claim", "", lane="lane/b", ids=["DEF-1"], now=self._T1)
        ship_b = _msg(mail, "win", "release", "", lane="lane/b", now=self._T2)
        live = mail.live_assignments({"air": [job], "win": [claim, ship_b]}, dispatcher="air")
        assert [m["id"] for m in live] == [job["id"]]
        ship_a = _msg(mail, "win", "release", "", lane="lane/a", now=self._T2)
        closed: list = []
        assert mail.live_assignments({"air": [job], "win": [claim, ship_b, ship_a]}, dispatcher="air",
                                     closed=closed) == []
        assert [rule for _a, _r, rule in closed] == ["lane"]

    _T3 = datetime(2026, 10, 9, 23, 0, 0, tzinfo=timezone.utc)

    def test_a_lane_begun_before_the_job_was_given_does_not_close_it(self, mail):
        """The seat's current lane touches a row the dispatcher has just queued
        as its next job, and the seat names the row on that lane's next claim:
        the lane was begun before the job, so its push leaves the job live
        (DEF-5003/5004's job on 2026-10-15 would have closed on the wrong push
        but for a re-send). Dies to: a claim counted by when it was sent rather
        than when its lane was begun."""
        begun = _msg(mail, "win", "claim", "", lane="lane/now", ids=["DEF-9"], now=self._T0)
        job = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1"], now=self._T1)
        touch = _msg(mail, "win", "claim", "", lane="lane/now", ids=["DEF-1"], now=self._T2)
        ship_now = _msg(mail, "win", "release", "", lane="lane/now", now=self._T3)
        live = mail.live_assignments({"air": [job], "win": [begun, touch, ship_now]}, dispatcher="air")
        assert [m["id"] for m in live] == [job["id"]]
        fix = _msg(mail, "win", "claim", "", lane="lane/fix", ids=["DEF-1"], now=self._T2)
        ship_fix = _msg(mail, "win", "release", "", lane="lane/fix", now=self._T3)
        assert mail.live_assignments({"air": [job], "win": [begun, touch, ship_now, fix, ship_fix]},
                                     dispatcher="air") == []

    def test_another_seats_start_of_the_same_lane_name_is_not_this_seats(self, mail):
        """The seat began the lane before the job; another seat began a lane of
        the same name after it. The seat's push reads its own start. Dies to: a
        lane's start kept by the lane alone."""
        early = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-9"], now=self._T0)
        job = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1"], now=self._T1)
        theirs = _msg(mail, "win-2", "claim", "", lane="lane/y", ids=["DEF-8"], now=self._T2)
        touch = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-1"], now=self._T2)
        ship = _msg(mail, "win", "release", "", lane="lane/y", now=self._T3)
        live = mail.live_assignments({"air": [job], "win": [early, touch, ship], "win-2": [theirs]},
                                     dispatcher="air")
        assert [m["id"] for m in live] == [job["id"]]

    def test_a_claim_released_by_its_id_does_not_move_the_lanes_start(self, mail):
        """A lane begins again only when no live claim is left on it, so a claim
        sent while another was live does not begin it, whichever is released
        first. Dies to: the start taken from the earliest claim still live."""
        first = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-9"], now=self._T0)
        job = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1"], now=self._T1)
        touch = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-1"], now=self._T2)
        drop = _msg(mail, "win", "release", "", ack=first["id"], now=self._T2)
        ship = _msg(mail, "win", "release", "", lane="lane/y", now=self._T3)
        live = mail.live_assignments({"air": [job], "win": [first, touch, drop, ship]}, dispatcher="air")
        assert [m["id"] for m in live] == [job["id"]]

    def test_a_follow_up_claim_on_a_lane_its_push_emptied_begins_the_lane_again(self, mail):
        """The edge the words name: a push releases the lane's claims, so a
        follow-up claim after the job came begins the lane again, and its push
        closes the job when its claims name the job's ids (inbox Step 2b and the
        protocol say so). Pins the fold as built: a lane is begun at its first
        claim since its claims last emptied."""
        first = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-9"], now=self._T0)
        push1 = _msg(mail, "win", "release", "", lane="lane/y", now=self._T1)
        job = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1"], now=self._T2)
        follow = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-1"], now=self._T2)
        push2 = _msg(mail, "win", "release", "", lane="lane/y", now=self._T3)
        closed: list = []
        live = mail.live_assignments({"air": [job], "win": [first, push1, follow, push2]}, dispatcher="air",
                                     closed=closed)
        assert live == [] and [rule for _a, _r, rule in closed] == ["claim"]

    def test_a_lane_emptied_and_begun_again_after_the_job_counts_from_its_new_start(self, mail):
        """A lane's start is its first live claim since its claims there last
        emptied, by a lane release or by a release of each claim's id. Dies to:
        a lane's start kept across a release that emptied it."""
        for emptied_by in ("lane", "id"):
            first = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-9"], now=self._T0)
            out = (_msg(mail, "win", "release", "", lane="lane/y", now=self._T0) if emptied_by == "lane"
                   else _msg(mail, "win", "release", "", ack=first["id"], now=self._T0))
            job = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1"], now=self._T1)
            again = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-1"], now=self._T2)
            ship = _msg(mail, "win", "release", "", lane="lane/y", now=self._T3)
            live = mail.live_assignments({"air": [job], "win": [first, out, again, ship]}, dispatcher="air")
            assert live == [], emptied_by

    def test_a_re_send_of_a_live_job_restarts_its_clock(self, mail):
        """A re-sent assign replaces the job and starts its clock again: a lane
        begun before the re-send no longer closes it, one begun after does.
        Dies to: the job's first assign read in place of its latest."""
        job = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1"], now=self._T0)
        early = _msg(mail, "win", "claim", "", lane="lane/x", ids=["DEF-1"], now=self._T1)
        resent = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1"], now=self._T2)
        ship = _msg(mail, "win", "release", "", lane="lane/x", now=self._T3)
        live = mail.live_assignments({"air": [job, resent], "win": [early, ship]}, dispatcher="air")
        assert [m["id"] for m in live] == [resent["id"]]
        again = _msg(mail, "win", "claim", "", lane="lane/y", ids=["DEF-1"], now=self._T2)
        ship_y = _msg(mail, "win", "release", "", lane="lane/y", now=self._T3)
        assert mail.live_assignments({"air": [job, resent], "win": [early, again, ship_y]},
                                     dispatcher="air") == []

    def test_a_malformed_assign_field_is_read_safely_where_its_own_seat_releases(self, mail):
        """The release loop reads the job's ids after the seat check, so only a
        release from the odd assign's own seat reaches that read. Dies to: the
        job's ids read raw in the release loop."""
        odd = _msg(mail, "air", "assign", "", seat="win-2", ids=["DEF-2"], now=self._T0)
        odd["re"]["ids"] = 5
        ship = _msg(mail, "win-2", "release", "", lane="lane/z", now=self._T1)
        live = mail.live_assignments({"air": [odd], "win-2": [ship]}, dispatcher="air")
        assert [m["id"] for m in live] == [odd["id"]]

    def test_a_release_naming_no_lane_closes_nothing_by_a_claim(self, mail):
        """Foreign data only (the writer refuses a release naming neither an id
        nor a lane): a claim with no lane is not on a release with no lane.
        Dies to: the claim rule read on a release that names no lane."""
        job = _msg(mail, "air", "assign", "", seat="win", ids=["DEF-1"], now=self._T0)
        claim = _msg(mail, "win", "claim", "", ids=["DEF-1"], paths=["a.py"], now=self._T1)
        bare = _msg(mail, "win", "release", "", lane="lane/x", now=self._T2)
        bare["re"]["lane"] = ""
        assert len(mail.live_assignments({"air": [job], "win": [claim, bare]}, dispatcher="air")) == 1

    def test_only_the_dispatcher_may_send_an_assign(self, mail, tmp_path, monkeypatch):
        """Dies to: a worker's assign accepted and then silently ignored."""
        monkeypatch.setattr(mail, "worktree_name_inherited", lambda root, run=None: False)
        (tmp_path / "espalier.toml").write_text('dispatcher = "air"\n', encoding="utf-8")
        assert mail.assign_refusal(tmp_path, "air") is None
        refusal = mail.assign_refusal(tmp_path, "win-2")
        assert refusal and "only the dispatcher (air) assigns" in refusal
        (tmp_path / "espalier.toml").write_text('dispatcher = "Air"\n', encoding="utf-8")
        assert "fix the dispatcher setting first" in (mail.assign_refusal(tmp_path, "air") or "")
        (tmp_path / "espalier.toml").unlink()
        assert mail.assign_refusal(tmp_path, "win-2") is None   # no dispatcher named: a lone operator assigns


class TestAssignShape:
    """TP-703e 1-B: an assign's shape (memory/parallel-work-protocol.md, "What an
    assign says") is a note on stderr, never a refusal: the text's length past
    ``ASSIGN_SHAPE_CHARS``, and each phrase of ``ASSIGN_SHAPE_WORDS`` it names
    (a hyphen read as a space, so ``full-tier`` is ``full tier``; the dispatcher's
    own ``Tier:`` and ``Review:`` forms among them), which the tier script prints
    from the diff, so the phrases are noted only where ``scripts/proof_tier.py``
    is on the tree (the driver deploys where it is not). Measured on the
    dispatcher's assigns of 2026-10-18: every one past 900 characters; the
    pack's Landing carries the phrase count."""

    def test_a_text_past_the_cap_gets_one_note_and_one_at_the_cap_gets_none(self, mail):
        """Dies to: the boundary off by one, or the count left out of the note."""
        assert mail.ASSIGN_SHAPE_CHARS == 900
        assert mail.assign_shape_notes("x" * 899) == []
        assert mail.assign_shape_notes("x" * 900) == []
        notes = mail.assign_shape_notes("x" * 901)
        assert len(notes) == 1 and "901 characters" in notes[0] and "900" in notes[0]

    def test_each_phrase_the_tier_script_prints_is_named_in_its_own_note(self, mail):
        """Dies to: the phrase not named, a case-sensitive match, a hyphen read as a
        letter, the dispatcher's own Tier: and Review: forms missed, two phrases in
        one note, or the phrases noted where the tier script is not."""
        notes = mail.assign_shape_notes("the job; Full Tier; why now")
        assert len(notes) == 1 and "'full tier'" in notes[0] and "scripts/proof_tier.py" in notes[0]
        notes = mail.assign_shape_notes("code-reviewer and failure-mode-reviewer, both reviewers")
        assert len(notes) == 3
        assert [n for n in notes if "'code-reviewer'" in n] and [n for n in notes if "'both reviewers'" in n]
        named = {p for n in mail.assign_shape_notes("Tier: hooks, so full-tier. Review: both")
                 for p in ("'tier:'", "'full tier'", "'review:'") if p in n}
        assert named == {"'tier:'", "'full tier'", "'review:'"}
        assert mail.assign_shape_notes("the job, why now, what it waits for") == []
        assert mail.assign_shape_notes("why now: full tier", phrases=False) == []

    def test_the_word_list_carries_every_tier_and_reviewer_the_tier_script_names(self, mail):
        """The list is a literal (the driver deploys where the tier script does
        not), pinned here against the script's own tuples so a renamed tier or
        reviewer reds. Dies to: a name added to the script and not to the list."""
        tier = _load(REPO_ROOT / "scripts" / "proof_tier.py", "proof_tier_for_the_shape_pin")
        # The rosters are hand-written and the script's tuples are the actual (FAILURE_MODES
        # 18.4): a renamed, added or dropped tier or reviewer is loud here, never a silent
        # narrowing of a loop derived from the subject.
        assert set(tier.TIERS) == {"full", "recall", "contract"}, tier.TIERS
        assert set(tier.REVIEWS) == {"none", "code-reviewer", "both"}, tier.REVIEWS
        words = set(mail.ASSIGN_SHAPE_WORDS)
        assert {"full tier", "recall tier", "contract tier", "code-reviewer", "both reviewers"} <= words
        assert all(w == w.lower() and w.isascii() for w in words)

    def test_the_cap_the_brief_and_the_prose_state_is_the_constant(self, mail):
        """The number lives in the constant, the self-host dispatcher brief, the
        protocol and two bodies; only the constant is code. Dies to: one copy
        moved without the others."""
        import re
        cap = mail.ASSIGN_SHAPE_CHARS
        seat = _load(REPO_ROOT / "tools" / "cc" / "seat.py", "seat_for_the_shape_pin")
        assert f"under {cap} characters" in seat.SELF_HOST_ASSIGN
        for rel in ("memory/parallel-work-protocol.md", ".claude/commands/inbox.md", "docs/WORKFLOW.md"):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            stated = re.findall(r"(?i)under (\d+)\s+characters", text)   # a wrap may fall between them
            assert stated and set(stated) == {str(cap)}, (rel, stated)

    def test_the_prose_has_a_seat_release_its_own_claims_by_id_never_by_lane(self, mail):
        """A lane release from a seat reads as its lane shipped and closes a job
        it was given (the third closing rule), so every recipe that has a seat
        release its own claims by hand (shrinking a claim, abandoning a lane)
        spells the release by id. Dies to: a recipe spelled with ``--lane``."""
        for rel in (".claude/commands/inbox.md", "memory/parallel-work-protocol.md"):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            assert "--type release --lane" not in text, rel
        inbox = (REPO_ROOT / ".claude" / "commands" / "inbox.md").read_text(encoding="utf-8")
        shrink = inbox[inbox.index("**A claim only grows.**"):][:700]
        assert "--ack <claim id>" in shrink, shrink

    def test_the_notes_never_refuse_and_print_beside_the_dry_run_count(self, mail, monkeypatch, tmp_path, capsys):
        """Dies to: a note raised as a refusal, the notes skipped on --dry-run or
        on a real send, the unstripped text counted, or the phrases noted on a
        tree without the tier script."""
        for odd in ("", "x" * 5000, "caf\u00e9 \u2014 full tier"):
            notes = mail.assign_shape_notes(odd)
            assert isinstance(notes, list) and all(isinstance(n, str) and n.isascii() for n in notes)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(mail, "worktree_name_inherited", lambda root, run=None: False)
        monkeypatch.setattr(mail, "machine_setting", lambda root, **kw: ("air", "git config espalier.machine = air"))
        (tmp_path / "espalier.toml").write_text('dispatcher = "air"\n', encoding="utf-8")
        tier_script = tmp_path / "scripts" / "proof_tier.py"   # the self-host tell, an empty stand-in
        tier_script.parent.mkdir()
        tier_script.write_text("", encoding="utf-8")
        body = tmp_path / "assign.txt"
        body.write_text("full tier " + "x" * 895 + "\n", encoding="utf-8")   # 905 characters once stripped
        argv = ["--root", str(tmp_path), "send", "--type", "assign", "--seat", "win", "--lane", "lane/x",
                "--text-file", str(body)]
        assert mail.main([*argv, "--dry-run"]) == 0
        out, err = capsys.readouterr()
        assert json.loads(out)["type"] == "assign"
        assert "note: the assign is 905 characters" in err and "'full tier'" in err
        assert f"body: 905 of {mail.MAX_TEXT} characters" in err
        sent: list[dict] = []
        monkeypatch.setattr(mail, "send", lambda root, message: sent.append(message))
        assert mail.main(argv) == 0 and sent and sent[0]["type"] == "assign"
        assert "note: the assign is 905 characters" in capsys.readouterr()[1]
        body.write_text("x" * 900 + "\n", encoding="utf-8")   # at the cap once stripped
        assert mail.main([*argv, "--dry-run"]) == 0
        err = capsys.readouterr()[1]
        assert "note: the assign" not in err and f"body: 900 of {mail.MAX_TEXT}" in err
        tier_script.unlink()   # an adopter tree: the length is noted, the phrases are not
        body.write_text("full tier " + "x" * 895, encoding="utf-8")
        assert mail.main([*argv, "--dry-run"]) == 0
        err = capsys.readouterr()[1]
        assert "note: the assign is 905 characters" in err and "'full tier'" not in err


class TestMachineSettingReads:
    def test_a_git_error_reads_as_unread_never_as_not_set(self, mail, tmp_path):
        """`git config --get` exits 1 for a key that is not set and 128 for a
        config git cannot read (a malformed file, a dubious-ownership refusal);
        the board then said "(no seat name)" and folded the real seat (both
        reviewers, TP-701 r4). Dies to: every nonzero exit read as not set."""
        unset = lambda argv, **kw: (1, "", "")  # noqa: E731
        broken = lambda argv, **kw: (128, "", "fatal: bad config line 3 in file .git/config")  # noqa: E731
        assert mail.machine_setting(tmp_path, run=unset) == (None, mail.machine_setting(tmp_path, run=unset)[1])
        assert not mail.machine_setting(tmp_path, run=unset)[1].startswith(mail.MACHINE_UNREAD)
        name, how = mail.machine_setting(tmp_path, run=broken)
        assert name is None and how.startswith(mail.MACHINE_UNREAD) and "bad config line 3" in how, how
        quiet = lambda argv, **kw: (128, "", "")  # noqa: E731
        assert "git exited 128: git exited 128" not in mail.machine_setting(tmp_path, run=quiet)[1]

    def test_an_unread_name_is_not_answered_with_turn_it_on(self, mail, tmp_path, monkeypatch, capsys):
        """`git config espalier.machine <name>` fails the same way on a config
        git cannot read, and on a timeout it would rename a seat that has a
        name (both reviewers, TP-701 r5). Dies to: the hint appended to an
        unread reason."""
        monkeypatch.setattr(mail, "machine_setting",
                            lambda root, **kw: (None, f"{mail.MACHINE_UNREAD} (took longer than 10s), so the channel is off"))
        assert mail.main(["--root", str(tmp_path), "claims", "--no-fetch"]) == 1
        err = capsys.readouterr().err
        assert mail.MACHINE_UNREAD in err and "turns it on" not in err, err
        monkeypatch.setattr(mail, "machine_setting", lambda root, **kw: (None, "git config espalier.machine is not set"))
        assert mail.main(["--root", str(tmp_path), "claims", "--no-fetch"]) == 1
        assert "turns it on" in capsys.readouterr().err


#: The one argv the readers use for the per-worktree config switch: the
#: repository's own config, read as a boolean (git's own reading of it).
_EXT_READ = ("config", "--local", "--type=bool", "--get", "extensions.worktreeConfig")


class TestTheNameReadersSayAFailedRead:
    """Every read of the machine name tells a read that failed (git timing
    out, a config git cannot parse) from a name that is not set: the clone's
    own read, a worktree's own, and the reads name_this_worktree makes.
    Driven with a fake git keyed by directory and argument list, since the
    failures are the thing under test."""

    @staticmethod
    def _failures(mail):
        """The two failures every case is driven with: a timeout, and a config git cannot parse."""
        return (mail.Unresolvable("git config took longer than 10s"),
                (128, "", "fatal: bad config line 3 in file .git/config"))

    @staticmethod
    def _git_at(by_cwd: dict, default: dict):
        """A fake git: ``by_cwd[str(cwd)][args]`` first, else ``default[args]``;
        a list answers in call order, an exception is raised."""
        def run(argv, cwd=None, **kw):
            key = tuple(argv[1:])
            table = by_cwd.get(str(cwd), {})
            answer = table[key] if key in table else default.get(key)
            if answer is None:
                raise AssertionError(f"unexpected call {argv} in {cwd}")
            if isinstance(answer, list):
                answer = answer.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer
        return run

    def test_the_clone_read_says_a_failed_read(self, mail, tmp_path):
        """Dies to clone_machine answering None alike where the clone names no
        machine and where git could not answer (DEF-5003's reader)."""
        key = ("config", "--local", "--get", "espalier.machine")
        for failed in self._failures(mail):
            name, how = mail.clone_machine(tmp_path, run=self._git_at({}, {key: failed}))
            assert name is None and how.startswith(mail.MACHINE_UNREAD), how
        name, how = mail.clone_machine(tmp_path, run=self._git_at({}, {key: (1, "", "")}))
        assert name is None and not how.startswith(mail.MACHINE_UNREAD), how
        assert mail.clone_machine(tmp_path, run=self._git_at({}, {key: (0, "win\n", "")}))[0] == "win"

    def test_a_worktree_read_with_the_extension_off_is_not_set(self, mail, tmp_path):
        """Measured on git 2.39.5: with several worktrees and
        extensions.worktreeConfig off, `git config --worktree --get` exits 128
        ("cannot be used with multiple working trees"). That is no worktree
        having a name of its own, not a failed read. Dies to the worktree
        scope reading every 128 as unread, which kept every worktree of a clone
        without the extension from SessionStart's clean-up."""
        ext = _EXT_READ
        own = ("config", "--worktree", "--get", "espalier.machine")
        refused = (128, "", "fatal: --worktree cannot be used with multiple working trees")
        name, how = mail.machine_setting(tmp_path, run=self._git_at({}, {ext: (1, "", ""), own: refused}),
                                         scope="worktree")
        assert name is None and not how.startswith(mail.MACHINE_UNREAD), how
        for failed in self._failures(mail):
            for answers in ({ext: failed}, {ext: (0, "true\n", ""), own: failed}):
                name, how = mail.machine_setting(tmp_path, run=self._git_at({}, answers), scope="worktree")
                assert name is None and how.startswith(mail.MACHINE_UNREAD), (answers, how)
        got = mail.machine_setting(tmp_path, run=self._git_at({}, {ext: (0, "true\n", ""), own: (0, "air-2\n", "")}),
                                   scope="worktree")
        assert got[0] == "air-2", got

    def test_a_failed_key_read_is_neither_answer(self, mail, tmp_path):
        """A read that failed is no evidence either way: it answered True,
        refusing a mint or an assign that had nothing wrong, where its key
        read exited 128, and False, letting an inherited name through, where
        git raised. Dies to either answer for a failed read (None now, and each
        caller says so), and to a refused hand-set value read as no name."""
        answers = {("rev-parse", "--git-dir"): (0, f"{tmp_path / 'gitdir'}\n", ""),
                   ("rev-parse", "--git-common-dir"): (0, f"{tmp_path / 'common'}\n", ""),
                   _EXT_READ: (0, "true\n", "")}
        own = ("config", "--worktree", "--get", "espalier.machine")
        for failed in self._failures(mail):
            for broken in ({**answers, own: failed}, {**answers, _EXT_READ: failed},
                           {**answers, ("rev-parse", "--git-dir"): failed}):
                assert mail.worktree_name_inherited(tmp_path, run=self._git_at({}, broken)) is None, (failed, broken)
        assert mail.worktree_name_inherited(tmp_path, run=self._git_at({}, {**answers, own: (1, "", "")})) is True
        assert mail.worktree_name_inherited(tmp_path, run=self._git_at({}, {**answers, own: (0, "Air-2\n", "")})) is False
        off = {**answers, _EXT_READ: (1, "", "")}
        assert mail.worktree_name_inherited(tmp_path, run=self._git_at({}, off)) is True

    def test_an_unread_inherited_check_is_said_and_refuses_an_assign(self, mail, tmp_path, monkeypatch):
        """Dies to the unread answer taken for "has a name of its own":
        SessionStart's naming then said nothing, and an assign went through."""
        (tmp_path / ".git").write_text("gitdir: x\n", encoding="utf-8")
        monkeypatch.setattr(mail, "worktree_name_inherited", lambda root, **kw: None)
        name, said = mail.name_this_worktree(tmp_path, run=self._git_at({}, {}))
        assert name is None and "could not be read" in said and "fix it first" in said, said
        (tmp_path / "espalier.toml").write_text('dispatcher = "air"\n', encoding="utf-8")
        refusal = mail.assign_refusal(tmp_path, "air", run=self._git_at({}, {})) or ""
        assert "could not be read" in refusal and "fix it first" in refusal, refusal

    def _naming(self, tmp_path, *, clone, sibling=(1, "", ""), back=(0, "air-wt\n", "")):
        """The git name_this_worktree meets in .claude-style worktree `wt` of a
        clone `air` with one other worktree `other`, extension on."""
        wt, other = tmp_path / "wt", tmp_path / "other"
        wt.mkdir()
        other.mkdir()
        (wt / ".git").write_text("gitdir: x\n", encoding="utf-8")
        own = ("config", "--worktree", "--get", "espalier.machine")
        default = {
            ("rev-parse", "--git-dir"): (0, f"{tmp_path / 'gitdir'}\n", ""),
            ("rev-parse", "--git-common-dir"): (0, f"{tmp_path / 'common'}\n", ""),
            _EXT_READ: (0, "true\n", ""),
            ("config", "--get", "espalier.machine"): clone,
            ("rev-parse", "--show-toplevel"): (0, f"{wt}\n", ""),
            ("config", "--get", "core.worktree"): (1, "", ""),
            ("config", "--get", "core.bare"): (0, "false\n", ""),
            ("worktree", "list", "--porcelain"): (0, f"worktree {wt}\nworktree {other}\n", ""),
            ("config", "--worktree", "espalier.machine", "air-wt"): (0, "", ""),
        }
        run = self._git_at({str(wt): {own: [(1, "", ""), back]}, str(other): {own: sibling}}, default)
        return wt, run

    def test_name_this_worktree_says_a_failed_clone_read(self, mail, tmp_path):
        """Dies to the failed read of the clone's name returning (None, ''),
        SessionStart's 'nothing to do', so a worktree that should be named
        stays on its clone's name in silence."""
        for failed in self._failures(mail):
            sub = tmp_path / type(failed).__name__
            sub.mkdir()
            wt, run = self._naming(sub, clone=failed)
            name, said = mail.name_this_worktree(wt, run=run)
            assert name is None and mail.MACHINE_UNREAD in said and "is not named" in said, said
            assert "fix it first" in said, said   # a config git cannot parse is not healed by a retry

    def test_name_this_worktree_refuses_when_a_siblings_name_cannot_be_read(self, mail, tmp_path):
        """Dies to an unreadable sibling read as 'not taken': two worktrees
        would then answer one name and write one mail ref."""
        for failed in self._failures(mail):
            sub = tmp_path / type(failed).__name__
            sub.mkdir()
            wt, run = self._naming(sub, clone=(0, "air\n", ""), sibling=failed)
            name, said = mail.name_this_worktree(wt, run=run)
            assert name is None and "could not be told" in said and mail.MACHINE_UNREAD in said, said

    def test_a_failed_read_back_is_named_as_one(self, mail, tmp_path):
        """Dies to a read-back that failed reported as a name that did not read
        back, which sends the operator looking at the wrong thing."""
        for failed in self._failures(mail):
            sub = tmp_path / type(failed).__name__
            sub.mkdir()
            wt, run = self._naming(sub, clone=(0, "air\n", ""), back=failed)
            name, said = mail.name_this_worktree(wt, run=run)
            assert name is None and "read-back failed" in said and mail.MACHINE_UNREAD in said, said
        wt, run = self._naming(tmp_path, clone=(0, "air\n", ""))
        assert mail.name_this_worktree(wt, run=run)[0] == "air-wt"


class TestNamingSteps:
    """The by-hand steps that name a linked worktree, one owner for every
    refusal that prints them. On a clone whose shared config sets core.bare
    (or core.worktree), naming a worktree takes ONE change, the key moved out
    of the shared config into the main worktree's config.worktree at the path
    the refusal computes, after which a fresh session turns per-worktree config
    on and names the worktree itself (dispatcher, f43314 (i'): rounds 6-8 each
    failed a two-change wording a different way; round 8 measured on git
    2.39.5 that the move alone, then SessionStart, names every worktree with
    each one healthy)."""

    @staticmethod
    def _git(values: dict):
        def run(argv, **kw):
            value = values.get(argv[-1])
            if isinstance(value, Exception):
                raise value
            if isinstance(value, tuple):
                return value
            return (0, value + "\n", "") if value is not None else (1, "", "")
        return run

    def test_a_plain_clone_gets_the_two_commands(self, mail, tmp_path):
        steps = mail.naming_steps(tmp_path, run=self._git({"core.bare": "false"}))
        assert steps == "git config extensions.worktreeConfig true, then git config --worktree espalier.machine <name>"

    def test_a_bare_clone_gets_one_change_at_its_path_then_a_fresh_session(self, mail, tmp_path):
        """Dies to: a second change, a command, the path not computed (the
        clone-git-directory phrase was met by the wrong file, round 8), or the
        fresh session dropped."""
        common = tmp_path / "repo.git"
        steps = mail.naming_steps(tmp_path, run=self._git({"core.bare": "true", "--git-common-dir": str(common)}))
        assert f"main worktree's config.worktree ({common.resolve() / 'config.worktree'})" in steps, steps
        assert "fresh session" in steps, steps
        assert "extensions.worktreeConfig" not in steps and "git config" not in steps, steps
        assert "core.worktree" in mail.naming_steps(tmp_path, run=self._git({"core.worktree": "/x"}))

    def test_a_core_bare_read_that_fails_prints_no_steps(self, mail, tmp_path):
        """A failed read fell through to the paste-ready pair, whose first
        command breaks every worktree of a bare clone (failure-mode review,
        r8, measured). Dies to: the failed read taken for "not bare"."""
        for answer in (mail.Unresolvable("git config took longer than 10s"), (128, "", "fatal: bad config line 3")):
            steps = mail.naming_steps(tmp_path, run=self._git({"core.bare": answer}))
            assert "no steps are printed" in steps, steps
            assert "extensions.worktreeConfig true" not in steps and "--worktree" not in steps, steps

    def test_the_assign_refusal_carries_the_steps(self, mail, tmp_path, monkeypatch):
        (tmp_path / "espalier.toml").write_text('dispatcher = "win"\n', encoding="utf-8")
        monkeypatch.setattr(mail, "worktree_name_inherited", lambda root, run=None: True)
        refusal = mail.assign_refusal(tmp_path, "win", run=self._git({"core.bare": "true"})) or ""
        assert refusal.endswith(mail.naming_steps(tmp_path, run=self._git({"core.bare": "true"}))), refusal

    @staticmethod
    def _worktree_git(root, toplevel, bare: bool):
        """The git reads name_this_worktree makes in a linked worktree that
        still answers its clone's name `air`."""
        answers = {
            ("rev-parse", "--git-dir"): (0, f"{root / 'gitdir'}\n", ""),
            ("rev-parse", "--git-common-dir"): (0, f"{root / 'common'}\n", ""),
            _EXT_READ: (1, "", ""),
            ("config", "--get", "espalier.machine"): (0, "air\n", ""),
            ("rev-parse", "--show-toplevel"): (0, f"{toplevel}\n", ""),
            ("config", "--get", "core.bare"): (0, "true\n" if bare else "false\n", ""),
            ("config", "--get", "core.worktree"): (1, "", ""),
            ("worktree", "list", "--porcelain"): (0, "", ""),
        }

        def run(argv, **kw):
            key = tuple(argv[1:])
            if key not in answers:
                raise AssertionError(f"unexpected call {argv}")
            return answers[key]
        return run

    def test_name_this_worktree_prints_the_one_owners_steps(self, mail, tmp_path):
        """A worktree whose directory derives no name got its own copy of the
        steps, without the core.bare step on a bare clone (failure-mode
        review, r6, driven). Dies to: name_this_worktree spelling its own."""
        (tmp_path / ".git").write_text("gitdir: x\n", encoding="utf-8")
        run = self._worktree_git(tmp_path, tmp_path / "___", bare=True)
        name, said = mail.name_this_worktree(tmp_path, run=run)
        assert name is None and mail.naming_steps(tmp_path, run=run) in said, said
        assert "core.bare" in said

    def test_name_this_worktrees_core_bare_refusal_gives_the_one_change(self, mail, tmp_path):
        """Dies to: a second change or a command in the refusal, or ", in
        <worktree>" covering the move (round 7: a move run in the linked
        worktree lands in that worktree's own file)."""
        (tmp_path / ".git").write_text("gitdir: x\n", encoding="utf-8")
        name, said = mail.name_this_worktree(tmp_path, run=self._worktree_git(tmp_path, tmp_path / "wt", bare=True))
        assert name is None and str((tmp_path / "common").resolve() / "config.worktree") in said, said
        assert "fresh session" in said and "extensions.worktreeConfig" not in said, said
        assert not said.endswith(f", in {tmp_path}"), said

    def test_name_this_worktree_hands_the_steps_the_value_it_read(self, mail, tmp_path):
        """A second read of core.bare that failed printed "sets core.bare" and
        then the plain pair (failure-mode review, r8). Dies to: naming_steps
        reading the key again."""
        (tmp_path / ".git").write_text("gitdir: x\n", encoding="utf-8")
        base = self._worktree_git(tmp_path, tmp_path / "wt", bare=True)
        reads = []

        def run(argv, **kw):
            if argv[1:] == ["config", "--get", "core.bare"]:
                reads.append(1)
                if len(reads) > 1:
                    raise mail.Unresolvable("git config took longer than 2s")
            return base(argv, **kw)

        name, said = mail.name_this_worktree(tmp_path, run=run)
        assert name is None and "fresh session" in said and "no steps are printed" not in said, said
        assert len(reads) == 1, reads


_NAMING_COMMAND = "extensions.worktreeConfig true"
_NAMING_SCOPES = ("lsewhere", "other clone", "not bare")


def _naming_prose_offenders(repo_root: Path, window: int = 700) -> tuple[int, list[str]]:
    """``(occurrences, offenders)`` of the command turning per-worktree config
    on, in the markdown under docs/, .claude/ and memory/ -- less Claude Code's
    worktrees under .claude/worktrees/, other checkouts on other commits
    (DEF-1196, ``tests/_live_tree.py``). An occurrence offends unless the
    nearest "bare clone" before it, within ``window`` characters, is followed
    by the other case that takes the one change ("core.worktree") and by
    words scoping the command away from both ("Elsewhere", "any other clone",
    "not bare")."""
    import re

    from espalier._safe_walk import visible
    from tests._live_tree import exclude_worktrees
    seen, bad = 0, []
    for root in (repo_root / d for d in ("docs", ".claude", "memory")):
        if not root.is_dir():
            continue
        for path in visible(exclude_worktrees(root.rglob("*.md"), repo_root), root):
            rel = path.relative_to(repo_root).as_posix()
            if rel.startswith("memory/session-log.d/"):
                continue   # a record: an old row is not rewritten
            text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))
            for m in re.finditer(re.escape(_NAMING_COMMAND), text):
                seen += 1
                before = text[max(0, m.start() - window):m.start()]
                at = before.rfind("bare clone")
                if at < 0 or "core.worktree" not in before[at:] or not any(
                        word in before[at:] for word in _NAMING_SCOPES):
                    bad.append(f"{rel}: ...{text[max(0, m.start() - 120):m.end()]}")
    return seen, bad


class TestNamingProse:
    """Every doc under docs/, .claude/ and memory/ that gives the command
    turning per-worktree config on names a bare clone shortly before it and
    then scopes the command away from one, so a reader on one does not run it
    first (both reviewers, TP-701 r8: four prose readers led with it; r9: any
    mention let the pre-fold WORKFLOW.md through, and a clone whose shared
    config sets core.worktree was told to run it). The population is derived
    from the tree, never listed by hand."""

    def test_the_command_is_preceded_by_its_bare_clone_condition(self):
        seen, bad = _naming_prose_offenders(REPO_ROOT)
        assert seen >= 4, f"only {seen} occurrences found: the walk lost its population"
        assert not bad, "the command with no bare-clone condition scoping it:\n" + "\n".join(bad)

    def test_a_linked_worktrees_copy_is_not_this_trees_prose(self, tmp_path):
        """A Claude Code worktree under .claude/worktrees/ is another checkout
        (DEF-1196); the doc beside it is read (both reviewers, r9: a seat at
        any commit holding the packs reds the walk). Dies to: the walk without
        exclude_worktrees."""
        line = "Run `git config extensions.worktreeConfig true` once.\n"
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "real.md").write_text(line, encoding="utf-8")
        planted = tmp_path / ".claude" / "worktrees" / "probe" / "docs"
        planted.mkdir(parents=True)
        (planted / "old.md").write_text(line, encoding="utf-8")
        seen, bad = _naming_prose_offenders(tmp_path)
        assert seen == 1 and len(bad) == 1 and bad[0].startswith("docs/real.md: "), bad

    def test_a_bare_clone_mention_must_scope_the_command_away(self, tmp_path):
        """Dies to: any mention of a bare clone nearby taken for the condition
        (the pre-fold WORKFLOW.md passed so, code review r9, measured), or the
        core.worktree case left out of it (failure-mode review r9)."""
        (tmp_path / "docs").mkdir()
        doc = tmp_path / "docs" / "w.md"
        doc.write_text("Name the clone (in a bare clone, in the repository; mind core.worktree). Run `git config "
                       "extensions.worktreeConfig true` once.\n", encoding="utf-8")
        assert _naming_prose_offenders(tmp_path)[1], "a mention alone passed"
        doc.write_text("On a bare clone, move core.bare out. Elsewhere, run `git config "
                       "extensions.worktreeConfig true` once.\n", encoding="utf-8")
        assert _naming_prose_offenders(tmp_path)[1], "the core.worktree case left out passed"
        doc.write_text("On a bare clone, or one whose shared config sets core.worktree, move that key out. "
                       "Elsewhere, run `git config extensions.worktreeConfig true` once.\n", encoding="utf-8")
        assert _naming_prose_offenders(tmp_path) == (1, [])


class TestLiveRequests:
    """TP-701 Wave A-1: the requests no ``ack`` answers, the dispatcher's
    unanswered asks. Pairing on the request's id, never on acks alone: on
    every mail ref read 2026-10-15, 37 of 92 acks answered a note, an ack or a
    claim (A-0 item 2), so "acks minus requests" is not the count."""

    _T0 = datetime(2026, 10, 14, 20, 0, 0, tzinfo=timezone.utc)
    _NOW = datetime(2026, 10, 15, 2, 30, 0, tzinfo=timezone.utc)

    def test_a_request_an_ack_names_is_answered_and_one_no_ack_names_is_live(self, mail):
        """Dies to: the ack pairing dropped (the answered request listed)."""
        asked = _msg(mail, "win", "request", "a", lane="lane/a", now=self._T0)
        open_ = _msg(mail, "win-2", "request", "b", now=self._T0.replace(minute=5))
        answer = _msg(mail, "air", "ack", "done", ack=asked["id"], now=self._T0.replace(minute=9))
        live = mail.live_requests({"win": [asked], "win-2": [open_], "air": [answer]}, now=self._NOW)
        assert [m["id"] for m in live] == [open_["id"]]

    def test_only_an_ack_answers_a_request(self, mail):
        """A note or a release whose ``ack`` field names the request is not its
        answer (one such note is on the live record). Dies to: any message
        carrying the id read as the answer."""
        asked = _msg(mail, "win", "request", "a", now=self._T0)
        note = _msg(mail, "air", "note", "seen", ack=asked["id"], now=self._T0.replace(minute=1))
        release = _msg(mail, "air", "release", "", ack=asked["id"], now=self._T0.replace(minute=2))
        live = mail.live_requests({"win": [asked], "air": [note, release]}, now=self._NOW)
        assert [m["id"] for m in live] == [asked["id"]]

    def test_an_ack_on_the_askers_own_ref_closes_it(self, mail):
        """The dispatcher's own acks live on its own ref, so a reader that
        leaves out its own machine would list every request it answered. Dies
        to: a machine's own ref excluded from the pairing."""
        asked = _msg(mail, "air", "request", "operator: which?", now=self._T0)
        closed = _msg(mail, "air", "ack", "answered in person", ack=asked["id"], now=self._T0.replace(minute=3))
        assert mail.live_requests({"air": [asked, closed]}, now=self._NOW) == []

    def test_oldest_first_across_machines_each_with_its_age(self, mail):
        """Dies to: the order by machine, or the age read from anything but
        the request's own stamp."""
        late = _msg(mail, "air", "request", "late", now=self._T0.replace(hour=23))
        early = _msg(mail, "win", "request", "early", now=self._T0)
        live = mail.live_requests({"air": [late], "win": [early]}, now=self._NOW)
        assert [(m["text"], m["age_s"]) for m in live] == [("early", 6 * 3600 + 1800), ("late", 3 * 3600 + 1800)]

    def test_the_fold_leaves_the_messages_it_read_untouched(self, mail):
        asked = _msg(mail, "win", "request", "a", now=self._T0)
        before = dict(asked)
        mail.live_requests({"win": [asked]}, now=self._NOW)
        assert asked == before

    def test_a_stamp_that_does_not_parse_has_no_age(self, mail):
        asked = _msg(mail, "win", "request", "a", now=self._T0)
        asked["at"] = "yesterday"
        assert mail.live_requests({"win": [asked]}, now=self._NOW)[0]["age_s"] is None


class TestTextFile:
    """TP-701 Wave A-4: ``send --text-file`` takes the body from a file, so a
    long or quote-heavy body never rides a shell string (an assign of 2,083
    characters cost the dispatcher a round trip at the cap, 2026-10-14). The
    whole file, UTF-8, exclusive with ``--text``; the dry run counts the body
    against the cap, and the cap itself is unchanged."""

    def _send(self, mail, monkeypatch, tmp_path, *args: str) -> int:
        monkeypatch.setattr(mail, "machine_setting", lambda root, **kw: ("mac", "git config espalier.machine = mac"))
        return mail.main(["--root", str(tmp_path), "send", "--type", "note", *args])

    def test_the_body_is_the_whole_file_and_the_dry_run_counts_it(self, mail, monkeypatch, tmp_path, capsys):
        """Dies to: the option missing, the file read in part, or the count left off."""
        body = tmp_path / "body.txt"
        text = "first line\nsecond line, \"quoted\" and `ticked` -- café\n"
        body.write_bytes(text.encode("utf-8"))
        assert self._send(mail, monkeypatch, tmp_path, "--text-file", str(body), "--dry-run") == 0
        out, err = capsys.readouterr()
        assert json.loads(out)["text"] == text.strip()
        assert f"body: {len(text.strip())} of {mail.MAX_TEXT} characters" in err

    def test_text_and_text_file_together_is_a_usage_error(self, mail, monkeypatch, tmp_path):
        body = tmp_path / "body.txt"
        body.write_text("x", encoding="utf-8")
        with pytest.raises(SystemExit) as stop:
            self._send(mail, monkeypatch, tmp_path, "--text", "y", "--text-file", str(body), "--dry-run")
        assert stop.value.code == 2

    def test_a_file_that_cannot_be_read_as_utf8_refuses_by_name(self, mail, monkeypatch, tmp_path, capsys):
        latin = tmp_path / "latin.txt"
        latin.write_bytes(b"caf\xe9\n")
        assert self._send(mail, monkeypatch, tmp_path, "--text-file", str(latin), "--dry-run") == 1
        assert "latin.txt" in capsys.readouterr().err
        assert self._send(mail, monkeypatch, tmp_path, "--text-file", str(tmp_path / "gone.txt"), "--dry-run") == 1
        assert "gone.txt" in capsys.readouterr().err

    def test_a_windows_saved_body_reads_with_lf_line_ends(self, mail, monkeypatch, tmp_path, capsys):
        """Two seats are Windows boxes: a CRLF file carried every CR into the
        body and paid one character per line against the cap (code review,
        r1). Dies to: the line ends kept."""
        body = tmp_path / "crlf.txt"
        body.write_bytes(b"one\r\ntwo\r\n")
        assert self._send(mail, monkeypatch, tmp_path, "--text-file", str(body), "--dry-run") == 0
        out, err = capsys.readouterr()
        assert json.loads(out)["text"] == "one\ntwo" and "body: 7 of" in err

    def test_the_cap_is_unchanged(self, mail, monkeypatch, tmp_path, capsys):
        long = tmp_path / "long.txt"
        long.write_text("x" * (mail.MAX_TEXT + 1), encoding="utf-8")
        assert self._send(mail, monkeypatch, tmp_path, "--text-file", str(long), "--dry-run") == 1
        assert f"the cap is {mail.MAX_TEXT}" in capsys.readouterr().err


class TestClaimSymbols:
    """TP-702 Wave 1 (1-B): a claim carries the symbols its lane changed under
    an optional key outside ``RE_KEYS`` (``SYMBOLS_KEY``, the ``ASSIGN_SEAT_KEY``
    precedent), written only when given, so an unflagged claim keeps today's
    ``re`` block byte for byte and a reader from before the key ignores it; the
    symbols' paths fill ``paths``, so a reader that knows only paths still meets
    the lane; the matcher meets a symbol by ``_symbols.symbols_meet``, the one
    rule. Each test names, in its docstring, the mutation it dies to."""

    def test_a_claim_with_symbols_round_trips_and_its_paths_fill_paths(self, mail):
        """Dies to: `paths` not filled from the symbols (a reader that knows only paths meets nothing)."""
        m = _msg(mail, "mac", "claim", "", lane="lane/x", paths=["docs/x.md"],
                 symbols=["tools/cc/mail.py::send", "tools/cc/mail.py::new_message", "tools/cc/board.py::render"])
        back = mail.decode_lines(mail.encode(m))[0][0]["re"]
        assert back[mail.SYMBOLS_KEY] == [
            "tools/cc/board.py::render", "tools/cc/mail.py::new_message", "tools/cc/mail.py::send"]
        assert back["paths"] == ["docs/x.md", "tools/cc/board.py", "tools/cc/mail.py"]
        assert list(back)[:4] == list(mail.RE_KEYS)

    def test_an_unflagged_claim_is_byte_identical_in_its_re_block(self, mail):
        """The expand step: a claim sent without symbols is today's, byte for byte. Dies to: the
        key written on every claim (an empty list)."""
        m = _msg(mail, "mac", "claim", "", lane="lane/x", paths=["a.py"], ids=["DEF-1"])
        assert '"re":{"lane":"lane/x","classes":[],"paths":["a.py"],"ids":["DEF-1"]},"text"' in mail.encode(m)

    def test_a_folder_the_cap_folded_keeps_its_symbols_and_one_given_by_hand_is_whole(self, mail):
        """``claim_view``, the one reading the matcher and the board share (TP-702 Wave 2). Dies to:
        a folder that carries symbols under it read as claimed whole (a lane past the path cap would
        never be certified), or a folder given by hand read as listed (a hand claim and a later
        symbol claim on one lane would be certified)."""
        rule = {mail.SYMBOLS_RULE_KEY: mail._symbols.RULE}
        _syms, _more, whole, _marked = mail.claim_view(
            {"paths": ["tools/cc"], mail.SYMBOLS_KEY: ["tools/cc/mail.py::send"], **rule})
        assert whole == set(), whole
        _syms, _more, whole, _marked = mail.claim_view({"paths": ["tools/cc", "docs"]})
        assert whole == {"tools/cc", "docs"}, whole
        _syms, _more, whole, _marked = mail.claim_view(
            {"paths": ["espalier/_vendor/cc/mail.py"], mail.SYMBOLS_KEY: ["espalier/_vendor/cc/mail.py::send"], **rule})
        assert whole == set() and _syms == {"tools/cc/mail.py::send"}, (whole, _syms)

    def test_a_claim_derived_by_another_rule_is_read_whole_and_a_new_one_is_stamped(self, mail):
        """Dies to: the rule left off a derived claim, a stamp written on symbols no derivation
        named (a hand list carries no marks, and would certify as complete), or a claim of an older
        or a newer rule read as a complete list (its list may lack, or spell differently, the
        neighbour and run-of-blanks marks a meeting needs)."""
        rule = mail._symbols.RULE
        m = _msg(mail, "mac", "claim", "", lane="l", symbols=["a.py::f"], symbols_rule=rule)
        assert m["re"][mail.SYMBOLS_RULE_KEY] == rule
        assert mail.SYMBOLS_RULE_KEY not in _msg(mail, "mac", "claim", "", lane="l", symbols=["a.py::f"])["re"]
        assert mail.SYMBOLS_RULE_KEY not in _msg(mail, "mac", "claim", "", lane="l", paths=["a.py"])["re"]
        for stamp in ({}, {mail.SYMBOLS_RULE_KEY: "0" * 16}, {mail.SYMBOLS_RULE_KEY: 3}):
            syms, _more, whole, _marked = mail.claim_view(
                {"paths": ["a.py"], mail.SYMBOLS_KEY: ["a.py::f"], **stamp})
            assert syms == {"a.py::f"} and whole == {"a.py"}, (stamp, whole)
            assert mail.other_rule({mail.SYMBOLS_KEY: ["a.py::f"], **stamp}), stamp
        assert not mail.other_rule({mail.SYMBOLS_KEY: ["a.py::f"], mail.SYMBOLS_RULE_KEY: rule})
        assert not mail.other_rule({"paths": ["a.py"]})   # a claim without symbols has no rule

    def test_two_claims_sharing_a_symbol_hit_by_the_symbol(self, mail):
        """Dies to: the symbol hit missing (two lanes in one function meet only as a path)."""
        theirs = _msg(mail, "win", "claim", "", lane="lane/w", symbols=["tools/cc/mail.py::send"])
        found = mail.overlapping_claims([theirs], symbols=["tools/cc/mail.py::send"])
        assert found[0][1] == ["symbol tools/cc/mail.py::send"], found

    def test_one_file_and_different_symbols_is_a_path_hit_and_says_so(self, mail):
        """No certificate in this wave: a shared file is a path hit, worded to say no symbol is
        shared. Dies to: the symbols compared by file (two functions in one file read as met)."""
        theirs = _msg(mail, "win", "claim", "", lane="lane/w", symbols=["tools/cc/mail.py::send"],
                      symbols_rule=mail._symbols.RULE)
        found = mail.overlapping_claims([theirs], symbols=["tools/cc/mail.py::headline"])
        assert found[0][1] == ["path tools/cc/mail.py (their tools/cc/mail.py; no symbol in common)"]
        # Placed under another rule, the same claim is no complete list: a path hit, no more.
        older = _msg(mail, "win", "claim", "", lane="lane/w", symbols=["tools/cc/mail.py::send"])
        assert mail.overlapping_claims([older], symbols=["tools/cc/mail.py::headline"])[0][1] == [
            "path tools/cc/mail.py (their tools/cc/mail.py)"]

    def test_a_class_covers_its_methods(self, mail):
        """Dies to: the matcher comparing names for equality only (`Board` and `Board.render`
        pass each other)."""
        theirs = _msg(mail, "win", "claim", "", lane="lane/w", symbols=["tools/cc/board.py::Board"])
        found = mail.overlapping_claims([theirs], symbols=["tools/cc/board.py::Board.render"])
        assert found[0][1] == ["symbol tools/cc/board.py::Board"]

    def test_a_claim_without_the_key_still_hits_by_path(self, mail):
        """An older seat's claim, or one sent without symbols. Dies to: the matcher keying on
        symbols alone (every such claim goes unmatched)."""
        theirs = _msg(mail, "win", "claim", "", lane="lane/w", paths=["tools/cc/mail.py"])
        found = mail.overlapping_claims([theirs], symbols=["tools/cc/mail.py::send"])
        assert found[0][1] == ["path tools/cc/mail.py (their tools/cc/mail.py)"]
        assert mail.overlapping_claims([theirs], paths=["tools/cc/mail.py"])[0][1] == [
            "path tools/cc/mail.py (their tools/cc/mail.py)"]

    def test_a_message_with_a_re_key_it_does_not_know_is_read(self, mail, capsys):
        """Task 0-D's reading, as a test: every reader takes the block's keys by name. Dies to: a
        reader that rejects a key it does not know, or reads a fixed key set over the block."""
        m = _msg(mail, "win", "claim", "", lane="lane/w", paths=["a.py"])
        m["re"]["from_a_later_writer"] = {"x": 1}
        msgs, skipped = mail.decode_lines(json.dumps(m) + "\n")
        assert skipped == 0 and msgs[0]["re"]["lane"] == "lane/w"
        live = mail.live_claims({"win": msgs})
        assert [c["id"] for c, _hits in mail.overlapping_claims(live, paths=["a.py"])] == [m["id"]]
        assert "lane/w" in mail.headline(msgs[0])
        mail._print_message(msgs[0])
        assert "lane: lane/w" in capsys.readouterr().out

    def test_symbols_belong_to_a_claim_and_name_a_repo_path(self, mail):
        """Dies to: the shape left unchecked (a note carrying symbols, a path outside the tree,
        a symbol with no name)."""
        with pytest.raises(mail.Unresolvable, match="claim"):
            _msg(mail, "mac", "note", "x", symbols=["a.py::f"])
        for bad in ("a.py", "::f", "/abs/a.py::f", "../up.py::f", "a.py::"):
            with pytest.raises(mail.Unresolvable):
                _msg(mail, "mac", "claim", "", lane="l", symbols=[bad])

    def test_the_cap_keeps_a_count_and_every_path(self, mail):
        """Dies to: the cap dropped (a line no listing can print), or the paths cut with the symbols."""
        many = [f"m{i // 10}.py::f{i}" for i in range(mail.MAX_SYMBOLS + 5)]
        m = _msg(mail, "mac", "claim", "", lane="l", symbols=many)
        assert len(m["re"][mail.SYMBOLS_KEY]) == mail.MAX_SYMBOLS
        assert m["re"][mail.SYMBOLS_MORE_KEY] == 5
        assert set(m["re"]["paths"]) == {s.split("::")[0] for s in many}

    def test_the_marks_ride_on_their_own_cap_after_the_names(self, mail):
        """Dies to: the marks sorted with the names (`<end>`, `<after:f>` and `<module>` sort before
        letters, so the listing led with them), or counted against the symbol cap (a lane's marks
        pushing a real symbol out, which reads every file of the lane whole)."""
        names = [f"a.py::f{i:03d}" for i in range(mail.MAX_SYMBOLS)]
        marks = ["a.py::<end>", "a.py::<after:f000>", "a.py::<module>"]
        m = _msg(mail, "mac", "claim", "", lane="l", symbols=marks + names)
        assert m["re"][mail.SYMBOLS_KEY] == sorted(names) + sorted(marks), m["re"][mail.SYMBOLS_KEY][:4]
        assert mail.SYMBOLS_MORE_KEY not in m["re"]
        many = [f"a.py::<after:f{i:03d}>" for i in range(mail.MAX_MARKS + 2)]
        m = _msg(mail, "mac", "claim", "", lane="l", symbols=["a.py::g", *many])
        assert m["re"][mail.SYMBOLS_MORE_KEY] == 2 and m["re"][mail.SYMBOLS_KEY][0] == "a.py::g"

    def test_a_symbol_path_the_guard_reads_as_secret_bearing_is_named(self, mail):
        """Dies to: the secret scan skipping the symbols (a block whose `paths` the symbol did not fill)."""
        m = _msg(mail, "mac", "claim", "", lane="l", symbols=["secrets/keys.py::load"])
        m["re"]["paths"] = []
        hits = mail.secret_hits(m)
        assert hits and "secrets/keys.py" in hits[0], hits

    def test_a_claim_cut_at_the_cap_never_says_no_symbol_in_common(self, mail):
        """The cap cut inside a file, and a plan naming a symbol past the cut was told no symbol
        was in common (code review, driven). Dies to: the clause printed beside a count of
        symbols the claim left out."""
        many = [f"a.py::f{i:03d}" for i in range(mail.MAX_SYMBOLS - 1)] + ["z.py::a", "z.py::b", "z.py::c"]
        theirs = _msg(mail, "win", "claim", "", lane="lane/w", symbols=many)
        assert theirs["re"][mail.SYMBOLS_MORE_KEY] == 2
        found = mail.overlapping_claims([theirs], symbols=["z.py::c"])
        assert found[0][1] == ["path z.py (their z.py)"], found

    def test_a_lane_split_over_a_claim_and_its_delta_is_read_as_one(self, mail):
        """A seat's first claim and its delta follow-up are one lane: the first claim was read
        alone and said no symbol in common while the delta named the symbol (code review,
        driven). Dies to: each claim matched on its own symbols only."""
        stamp = datetime(2026, 10, 17, 4, 0, 0, tzinfo=timezone.utc)
        first = _msg(mail, "win", "claim", "", lane="lane/w", symbols=["t/m.py::a"], now=stamp)
        delta = _msg(mail, "win", "claim", "", lane="lane/w", symbols=["t/m.py::b"], now=stamp.replace(minute=5))
        found = mail.overlapping_claims([first, delta], symbols=["t/m.py::b"])
        assert [(c["id"], hits) for c, hits in found] == [(delta["id"], ["symbol t/m.py::b"])], found

    def test_a_file_the_lane_claims_whole_never_says_no_symbol_in_common(self, mail):
        """A hand claim on a file is a claim on all of it, and the seat's own later delta named
        one function there: the clause then read as two functions apart (failure-mode review,
        driven). Dies to: the clause given wherever the lane names a symbol in the file."""
        stamp = datetime(2026, 10, 17, 5, 0, 0, tzinfo=timezone.utc)
        whole = _msg(mail, "win", "claim", "", lane="lane/w", paths=["tools/cc/mail.py"], now=stamp)
        delta = _msg(mail, "win", "claim", "", lane="lane/w", symbols=["tools/cc/mail.py::send"],
                     now=stamp.replace(minute=5))
        found = mail.overlapping_claims([whole, delta], symbols=["tools/cc/mail.py::headline"])
        assert [hits for _c, hits in found] == [["path tools/cc/mail.py (their tools/cc/mail.py)"]] * 2, found

    def test_a_file_with_unplaced_lines_never_says_no_symbol_in_common(self, mail):
        """`path::<module>` is a line no definition holds (an import, a lone comment): the pair
        reading calls that unplaced, so the matcher may not call it apart. Dies to: the clause
        given beside the lane's own unplaced marker for the file."""
        theirs = _msg(mail, "win", "claim", "", lane="lane/w",
                      symbols=["tools/cc/mail.py::send", "tools/cc/mail.py::<module>"])
        found = mail.overlapping_claims([theirs], symbols=["tools/cc/mail.py::headline"])
        assert found[0][1] == ["path tools/cc/mail.py (their tools/cc/mail.py)"], found

    def test_the_vendored_twin_meets_its_source_on_both_sides(self, mail):
        """The writer folds a twin onto its source; the reader did not, and a plan naming the
        vendored copy met nothing (failure-mode review, driven). Dies to: our side left unfolded."""
        theirs = _msg(mail, "win", "claim", "", lane="lane/w", symbols=["tools/cc/mail.py::send"])
        assert mail.overlapping_claims([theirs], symbols=["espalier/_vendor/cc/mail.py::send"])[0][1] == [
            "symbol tools/cc/mail.py::send"]
        hand = _msg(mail, "win", "claim", "", lane="lane/v", paths=["espalier/_vendor/cc/board.py"])
        assert mail.overlapping_claims([hand], paths=["tools/cc/board.py"])[0][1] == [
            "path tools/cc/board.py (their espalier/_vendor/cc/board.py)"]

    def test_a_malformed_list_from_another_seat_costs_itself(self, mail, capsys):
        """`symbols: 5` from another seat's ref raised in every reader, the ledger verbs' id
        refusal among them, which then wrote without it (failure-mode review, driven). Dies to:
        a list field read without its shape checked."""
        for bad in (5, True, 1.5, "tools/cc/mail.py::send", {"x": 1}):
            m = _msg(mail, "win", "claim", "", lane="lane/w", paths=["a.py"], ids=["DEF-1"])
            m["re"][mail.SYMBOLS_KEY] = bad
            assert [h for _c, h in mail.overlapping_claims([m], ids=["DEF-1"])] == [["id DEF-1"]], bad
            assert mail.overlapping_claims([m], symbols=["a.py::f"])[0][1] == ["path a.py (their a.py)"], bad
            mail._print_message(m)
        assert "lane: lane/w" in capsys.readouterr().out

    def test_a_malformed_count_from_another_seat_prints_as_none(self, mail, capsys):
        """Another seat's ref is text this reader did not write. Dies to: the count read with a
        bare `int` (every listing of every reader is a traceback)."""
        m = _msg(mail, "win", "claim", "", lane="lane/w", symbols=["a.py::f"])
        m["re"][mail.SYMBOLS_MORE_KEY] = "many"
        mail._print_message(m)
        assert "    symbols: a.py::f" in capsys.readouterr().out

    def test_the_listing_prints_eight_symbols_then_a_count(self, mail, capsys):
        """Dies to: every symbol printed (a claim of a hundred floods the listing), or none."""
        m = _msg(mail, "mac", "claim", "", lane="l", symbols=[f"a.py::f{i:02d}" for i in range(11)])
        mail._print_message(m)
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip().startswith("symbols:")]
        assert lines == ["    symbols: " + ", ".join(f"a.py::f{i:02d}" for i in range(8)) + " (+3 more)"]


class TestSymbolsFromTheLane:
    """`send --symbols-from <base>` derives a claim's symbols and paths from the
    lane's diff against the merge-base with the base (`_symbols.symbols_of_lane`);
    `--delta` sends only what no live claim of this seat on the lane already
    names, says so and sends nothing when nothing is new, and sends nothing once
    the lane's claims are released, so a lane fixing CI after its push never
    re-opens the claim the push closed."""

    PLACEMENTS = {
        "tools/cc/mail.py": {"kind": "python", "symbols": {"tools/cc/mail.py::send", "tools/cc/mail.py::new_message"},
                             "changed": 4, "unplaced": 0},
        "docs/x.md": {"kind": "path", "symbols": {"docs/x.md"}, "changed": 0, "unplaced": 0},
    }

    def _run(self, mail, monkeypatch, tmp_path, own, *args: str):
        sent: list[dict] = []
        seen: list[str] = []

        def lane(root, base, **kw):
            seen.append(base)
            return {k: dict(v, symbols=set(v["symbols"])) for k, v in self.PLACEMENTS.items()}

        monkeypatch.setattr(mail, "machine_setting", lambda root, **kw: ("mac", "git config espalier.machine = mac"))
        monkeypatch.setattr(mail._symbols, "symbols_of_lane", lane)
        monkeypatch.setattr(mail, "read_mail", lambda root, **kw: ({"mac": list(own)}, {}))
        monkeypatch.setattr(mail, "send", lambda root, message, **kw: sent.append(message))
        rc = mail.main(["--root", str(tmp_path), "send", *args])
        return rc, sent, seen

    def test_the_claim_carries_the_lane_s_symbols_and_paths(self, mail, monkeypatch, tmp_path):
        """Dies to: the flag read and the derivation never sent (a claim with no symbols)."""
        rc, sent, seen = self._run(mail, monkeypatch, tmp_path, [], "--type", "claim", "--lane", "lane/x",
                                   "--symbols-from", "origin/main")
        assert rc == 0 and seen == ["origin/main"]
        assert sent[0]["re"][mail.SYMBOLS_KEY] == ["tools/cc/mail.py::new_message", "tools/cc/mail.py::send"]
        assert sent[0]["re"]["paths"] == ["docs/x.md", "tools/cc/mail.py"]

    def test_the_delta_sends_only_what_no_live_claim_of_this_seat_names(self, mail, monkeypatch, tmp_path, capsys):
        """Dies to: the delta filter removed (every refresh resends the lane's whole set)."""
        own = [_msg(mail, "mac", "claim", "", lane="lane/x", symbols=["tools/cc/mail.py::send"],
                    symbols_rule=mail._symbols.RULE)]
        args = ("--type", "claim", "--lane", "lane/x", "--symbols-from", "origin/main", "--delta")
        rc, sent, _ = self._run(mail, monkeypatch, tmp_path, own, *args)
        assert rc == 0 and sent[0]["re"][mail.SYMBOLS_KEY] == ["tools/cc/mail.py::new_message"]
        assert "docs/x.md" in sent[0]["re"]["paths"]
        own.append(sent[0])
        rc, again, _ = self._run(mail, monkeypatch, tmp_path, own, *args)
        assert rc == 0 and again == [] and "no new symbols" in capsys.readouterr().out

    def test_a_claim_of_another_rule_is_named_no_symbol_and_its_release_is_asked_for(
            self, mail, monkeypatch, tmp_path, capsys):
        """The first delta after a rule change. Dies to: an older-rule claim's symbols counted as
        named (the delta prints "no new symbols" over a list every reader takes whole), its paths
        counted as claimed (the delta carries the symbols and not `docs/x.md`, which the release the
        note asks for leaves claimed by no one; both reviews of Wave 2's last delta, driven), the new
        claim left unstamped, or the seat not told which claim keeps its files whole."""
        old = _msg(mail, "mac", "claim", "", lane="lane/x", symbols=["tools/cc/mail.py::send"],
                   paths=["docs/x.md"])
        rc, sent, _ = self._run(mail, monkeypatch, tmp_path, [old], "--type", "claim", "--lane", "lane/x",
                                "--symbols-from", "origin/main", "--delta")
        assert rc == 0 and sent, sent
        assert sent[0]["re"][mail.SYMBOLS_KEY] == ["tools/cc/mail.py::new_message", "tools/cc/mail.py::send"]
        assert "docs/x.md" in sent[0]["re"]["paths"], sent[0]["re"]
        assert sent[0]["re"][mail.SYMBOLS_RULE_KEY] == mail._symbols.RULE
        err = capsys.readouterr().err
        assert old["id"] in err and "another symbol rule" in err and "release" in err, err

    def test_a_whole_claim_names_the_older_claims_it_replaces_and_only_those(
            self, mail, monkeypatch, tmp_path, capsys):
        """Without --delta too: the new claim is united with the older one on the lane, which keeps
        its files whole until released. Dies to: the note asked for on the delta only, or for a
        claim of this rule (the code review of Wave 2's last delta: both survived as mutants)."""
        old = _msg(mail, "mac", "claim", "", lane="lane/x", symbols=["tools/cc/mail.py::send"])
        stamped = _msg(mail, "mac", "claim", "", lane="lane/x", symbols=["tools/cc/mail.py::send"],
                       symbols_rule=mail._symbols.RULE)
        args = ("--type", "claim", "--lane", "lane/x", "--symbols-from", "origin/main")
        rc, sent, _ = self._run(mail, monkeypatch, tmp_path, [old, stamped], *args)
        err = capsys.readouterr().err
        assert rc == 0 and sent and old["id"] in err and stamped["id"] not in err, err
        rc, sent, _ = self._run(mail, monkeypatch, tmp_path, [stamped], *args)
        assert rc == 0 and sent and "another symbol rule" not in capsys.readouterr().err

    def test_a_path_an_older_claim_held_by_hand_rides_the_claim_that_replaces_it(self, mail, monkeypatch, tmp_path):
        """Dies to: an older-rule claim's hand path, which the lane's diff does not name, left off
        the claim that replaces it (the release the note asks for leaves it claimed by no one; the
        code review of Wave 2's sixth delta, driven), or one a claim of this rule covers re-sent."""
        old = _msg(mail, "mac", "claim", "", lane="lane/x", symbols=["tools/cc/mail.py::send"],
                   paths=["docs/plan.md"])
        args = ("--type", "claim", "--lane", "lane/x", "--symbols-from", "origin/main")
        for extra in ((), ("--delta",)):
            rc, sent, _ = self._run(mail, monkeypatch, tmp_path, [old], *args, *extra)
            assert rc == 0 and "docs/plan.md" in sent[0]["re"]["paths"], (extra, sent)
        current = _msg(mail, "mac", "claim", "", lane="lane/x", paths=["docs/x.md", "docs/plan.md"],
                       symbols=["tools/cc/mail.py::send", "tools/cc/mail.py::new_message"],
                       symbols_rule=mail._symbols.RULE)
        rc, sent, _ = self._run(mail, monkeypatch, tmp_path, [old, current], *args, "--delta")
        assert rc == 0 and sent == [], sent

    @pytest.mark.parametrize("held", ["tools/cc/mail.py", "tools/cc"], ids=["a-file-the-lane-changes", "a-folder"])
    @pytest.mark.parametrize("extra", [(), ("--delta",)], ids=["whole", "delta"])
    def test_what_an_older_claim_held_whole_stays_whole_on_the_claim_that_replaces_it(
            self, mail, monkeypatch, tmp_path, held, extra):
        """Dies to: a path the seat held whole by hand dropped from the replacing claim because
        the lane's diff names it, or symbols sit under it (the lane's symbols in it are sent
        instead, and once the older claim is released the pair reads "different functions";
        both reviews of Wave 2's seventh delta, driven)."""
        old = _msg(mail, "mac", "claim", "", lane="lane/x", symbols=["scripts/x.py::f"], paths=[held])
        rc, sent, _ = self._run(mail, monkeypatch, tmp_path, [old], "--type", "claim", "--lane", "lane/x",
                                "--symbols-from", "origin/main", *extra)
        assert rc == 0 and held in sent[0]["re"]["paths"], sent
        assert not [s for s in sent[0]["re"].get(mail.SYMBOLS_KEY, []) if s.startswith("tools/cc/mail.py::")], sent

    def test_a_file_an_older_claim_named_symbols_in_is_derived_again_not_carried(self, mail, monkeypatch, tmp_path):
        """Dies to: every path of the older claim carried (a file the lane has since reverted is
        held whole until the lane ships, and a claim the path cap folded refuses on every tick;
        the code review of Wave 2's seventh delta, driven)."""
        old = _msg(mail, "mac", "claim", "", lane="lane/x", symbols=["a.py::f"])
        rc, sent, _ = self._run(mail, monkeypatch, tmp_path, [old], "--type", "claim", "--lane", "lane/x",
                                "--symbols-from", "origin/main")
        assert rc == 0 and "a.py" not in sent[0]["re"]["paths"], sent

    def test_an_older_claim_s_ids_and_classes_ride_the_claim_that_replaces_it(
            self, mail, monkeypatch, tmp_path, capsys):
        """Dies to: the ids and classes of the claim the note asks to release left behind (the
        ledger verbs and the plan warnings meet a row or a class by them; the code review of Wave 2's
        seventh delta, driven), or the delta sending again what a claim of this rule already names."""
        old = _msg(mail, "mac", "claim", "", lane="lane/x", symbols=["tools/cc/mail.py::send"], ids=["DEF-1"],
                   classes=["cli-deploy"])
        args = ("--type", "claim", "--lane", "lane/x", "--symbols-from", "origin/main")
        rc, sent, _ = self._run(mail, monkeypatch, tmp_path, [old], *args)
        assert rc == 0 and "DEF-1" in sent[0]["re"]["ids"] and "cli-deploy" in sent[0]["re"]["classes"], sent
        current = dict(sent[0], id="c-current")
        capsys.readouterr()
        rc, again, _ = self._run(mail, monkeypatch, tmp_path, [old, current], *args, "--delta")
        out = capsys.readouterr()
        assert rc == 0 and again == [] and "no new symbols" in out.out, again
        assert old["id"] in out.err and "hold all of it" in out.err, out.err

    def test_a_folder_is_not_held_by_a_file_under_it(self, mail, monkeypatch, tmp_path):
        """Dies to: the delta's cover test read both ways (a folder the older claim held whole is
        dropped as covered by one file of this rule under it, and after the release no one holds
        the rest of the folder; the failure-mode review of Wave 2's seventh delta, driven)."""
        old = _msg(mail, "mac", "claim", "", lane="lane/x", symbols=["scripts/x.py::f"], paths=["tools/cc"])
        current = _msg(mail, "mac", "claim", "", lane="lane/x", paths=["tools/cc/mail.py", "docs/x.md"],
                       symbols=["tools/cc/mail.py::send", "tools/cc/mail.py::new_message"],
                       symbols_rule=mail._symbols.RULE)
        rc, sent, _ = self._run(mail, monkeypatch, tmp_path, [old, current], "--type", "claim", "--lane", "lane/x",
                                "--symbols-from", "origin/main", "--delta")
        assert rc == 0 and sent and "tools/cc" in sent[0]["re"]["paths"], sent

    def test_a_folder_an_older_claim_was_folded_into_covers_nothing_on_the_delta(self, mail, monkeypatch, tmp_path):
        """Dies to: the delta counting an older-rule claim's paths as claimed (a folder the path
        cap folded the older claim into, with symbols under it, is derived again and not carried,
        so a changed file under it that names no symbol goes unsent, and is held by no one once
        the older claim is released)."""
        old = _msg(mail, "mac", "claim", "", lane="lane/x", symbols=["docs/gen.py::f"], paths=["docs"])
        rc, sent, _ = self._run(mail, monkeypatch, tmp_path, [old], "--type", "claim", "--lane", "lane/x",
                                "--symbols-from", "origin/main", "--delta")
        assert rc == 0 and "docs/x.md" in sent[0]["re"]["paths"] and "docs" not in sent[0]["re"]["paths"], sent

    def test_a_failed_read_for_the_note_costs_the_note_never_the_claim(self, mail, monkeypatch, tmp_path, capsys):
        """Dies to: the note's read let out of the send (a claim that went out before refused for
        a line of advice; the failure-mode review of Wave 2's last delta)."""
        def broken(root, **kw):
            raise mail.Unresolvable("git for-each-ref failed")

        sent: list[dict] = []
        monkeypatch.setattr(mail, "machine_setting", lambda root, **kw: ("mac", "git config espalier.machine = mac"))
        monkeypatch.setattr(mail._symbols, "symbols_of_lane", lambda root, base, **kw: {
            k: dict(v, symbols=set(v["symbols"])) for k, v in self.PLACEMENTS.items()})
        monkeypatch.setattr(mail, "read_mail", broken)
        monkeypatch.setattr(mail, "send", lambda root, message, **kw: sent.append(message))
        rc = mail.main(["--root", str(tmp_path), "send", "--type", "claim", "--lane", "lane/x",
                        "--symbols-from", "origin/main"])
        assert rc == 0 and sent and "could not be read" in capsys.readouterr().err

    def test_the_delta_after_the_lane_s_release_sends_nothing(self, mail, monkeypatch, tmp_path, capsys):
        """Dies to: the release check removed (a lane fixing CI after its push re-opens the
        claim the push closed)."""
        claim = _msg(mail, "mac", "claim", "", lane="lane/x", symbols=["tools/cc/mail.py::send"])
        release = _msg(mail, "mac", "release", "", lane="lane/x")
        rc, sent, _ = self._run(mail, monkeypatch, tmp_path, [claim, release], "--type", "claim", "--lane",
                                "lane/x", "--symbols-from", "origin/main", "--delta")
        assert rc == 0 and sent == [] and "no live claim on this lane" in capsys.readouterr().out

    def test_the_delta_reads_the_seat_s_claims_before_the_lane(self, mail, monkeypatch, tmp_path, capsys):
        """A released lane exits 0 without a derivation (whose base read can need the network):
        the exit a refresh on every tick relies on (code review). Dies to: the lane derived first,
        so a failed base read refuses where nothing was ever to be sent."""
        claim = _msg(mail, "mac", "claim", "", lane="lane/x", paths=["a.py"])
        release = _msg(mail, "mac", "release", "", lane="lane/x")

        def no_base(root, base, **kw):
            raise mail.Unresolvable("the base could not be read")

        rc, sent, _ = self._run_with(mail, monkeypatch, tmp_path, [claim, release], no_base,
                                     "--type", "claim", "--lane", "lane/x", "--symbols-from", "origin/main", "--delta")
        assert rc == 0 and sent == [] and "no live claim on this lane" in capsys.readouterr().out

    def test_a_bare_symbols_from_reads_the_base_the_ship_driver_names(self, mail, monkeypatch, tmp_path):
        """Dies to: the bare flag read as an empty base (git refuses an empty revision)."""
        monkeypatch.setattr(mail, "_ship_default_base", lambda: "origin/trunk")
        rc, sent, seen = self._run(mail, monkeypatch, tmp_path, [], "--type", "claim", "--lane", "lane/x",
                                   "--symbols-from")
        assert rc == 0 and seen == ["origin/trunk"] and sent
        # The derivation stamps its rule (the one place a claim's symbols come from).
        assert sent[0]["re"][mail.SYMBOLS_RULE_KEY] == mail._symbols.RULE

    def test_a_lane_past_the_path_cap_folds_its_derived_paths_into_directories(self, mail, monkeypatch,
                                                                                 tmp_path, capsys):
        """Seventy changed files refused the claim outright, and a refresh every tick would fail
        on such a lane (code review, driven). A directory claims what is under it, so the derived
        paths fold to their directories until they fit, and the claim says so. Dies to: the
        derived paths sent whole into the cap."""
        files = [f"pkg/m{i // 10}/f{i}.py" for i in range(70)]
        placements = {p: {"kind": "python", "symbols": {f"{p}::f"}, "changed": 1, "unplaced": 0} for p in files}
        rc, sent, _ = self._run_with(mail, monkeypatch, tmp_path, [], lambda root, base, **kw: placements,
                                     "--type", "claim", "--lane", "lane/x", "--symbols-from", "origin/main")
        assert rc == 0 and len(sent) == 1, capsys.readouterr()
        paths = sent[0]["re"]["paths"]
        assert len(paths) <= mail.MAX_PATHS and all(any(mail._touches(f, p) for p in paths) for f in files)
        assert "folded" in capsys.readouterr().err

    def _run_with(self, mail, monkeypatch, tmp_path, own, lane, *args: str, others=None):
        sent: list[dict] = []
        monkeypatch.setattr(mail, "machine_setting", lambda root, **kw: ("mac", "git config espalier.machine = mac"))
        monkeypatch.setattr(mail._symbols, "symbols_of_lane", lane)
        monkeypatch.setattr(mail, "read_mail", lambda root, **kw: ({"mac": list(own), **(others or {})}, {}))
        monkeypatch.setattr(mail, "send", lambda root, message, **kw: sent.append(message))
        rc = mail.main(["--root", str(tmp_path), "send", *args])
        return rc, sent, []

    def test_a_path_given_by_hand_is_claimed_whole(self, mail, monkeypatch, tmp_path):
        """A hand `--path` beside the derivation claims the whole file, so the claim carries no
        symbols there that would let a reader call another function apart from it (failure-mode
        review). Dies to: the derived symbols kept inside a file the seat claimed whole."""
        rc, sent, _ = self._run(mail, monkeypatch, tmp_path, [], "--type", "claim", "--lane", "lane/x",
                                "--symbols-from", "origin/main", "--path", "tools/cc/mail.py")
        assert rc == 0 and mail.SYMBOLS_KEY not in sent[0]["re"], sent[0]["re"]
        assert sent[0]["re"]["paths"] == ["tools/cc/mail.py", "docs/x.md"]

    def test_the_delta_past_the_path_cap_folds_on_every_tick(self, mail, monkeypatch, tmp_path):
        """The first claim folded seventy files into directories; the next tick's delta re-added
        every new symbol's file and was refused at the cap, every tick (failure-mode review,
        driven). Dies to: the delta's symbol files kept out of the fold."""
        files = [f"pkg/m{i // 10}/f{i}.py" for i in range(70)]

        def lane_with(*names):
            return lambda root, base, **kw: {
                p: {"kind": "python", "symbols": {f"{p}::{n}" for n in names}, "changed": 1, "unplaced": 0}
                for p in files}

        args = ("--type", "claim", "--lane", "lane/x", "--symbols-from", "origin/main")
        rc, first, _ = self._run_with(mail, monkeypatch, tmp_path, [], lane_with("f"), *args)
        assert rc == 0 and first
        rc, second, _ = self._run_with(mail, monkeypatch, tmp_path, first, lane_with("f", "g"), *args, "--delta")
        assert rc == 0 and second, second
        assert len(second[0]["re"]["paths"]) <= mail.MAX_PATHS
        assert {s.rsplit("::", 1)[1] for s in second[0]["re"][mail.SYMBOLS_KEY]} == {"g"}

    def test_a_delta_on_a_lane_this_seat_never_claimed_is_refused_by_name(self, mail, monkeypatch, tmp_path,
                                                                            capsys):
        """`no live claim on this lane`, exit 0, read the same for a released lane and a lane
        name never claimed (a typo, a lane named one way and claimed another): a refresh would say
        it forever (failure-mode review, driven). Dies to: the two read as one."""
        elsewhere = _msg(mail, "mac", "claim", "", lane="lane/y", paths=["a.py"])
        rc, sent, _ = self._run_with(mail, monkeypatch, tmp_path, [elsewhere], lambda root, base, **kw: {},
                                     "--type", "claim", "--lane", "lane/x", "--symbols-from", "origin/main", "--delta")
        err = capsys.readouterr().err
        assert rc == 1 and sent == [] and "lane/x" in err and "lane/y" in err, err

    def test_another_seat_s_claim_on_the_lane_is_not_this_seat_s(self, mail, monkeypatch, tmp_path, capsys):
        """Dies to: the delta's own-machine filter dropped (another seat's claim on a lane of the
        same name read as this seat's, and its symbols left out of this seat's claim)."""
        theirs = _msg(mail, "win", "claim", "", lane="lane/x", paths=["a.py"])
        rc, sent, _ = self._run_with(mail, monkeypatch, tmp_path, [], lambda root, base, **kw: {},
                                     "--type", "claim", "--lane", "lane/x", "--symbols-from", "origin/main", "--delta",
                                     others={"win": [theirs]})
        assert rc == 1 and sent == [], capsys.readouterr()

    def test_the_fold_counts_the_paths_it_folded(self, mail):
        """Dies to: every derived path counted as folded (a note saying 68 where 5 folded)."""
        derived = [f"a{i}.py" for i in range(60)] + [f"d/x{i}.py" for i in range(10)]
        paths, folded = mail.fit_paths([], derived)
        assert folded == 10 and len(paths) == 61 and "d" in paths

    def test_the_flags_go_with_a_claim_on_a_lane(self, mail, monkeypatch, tmp_path, capsys):
        """Dies to: the flags taken on any message, or a delta with no lane to compare against."""
        for args in (("--type", "note", "--text", "x", "--symbols-from", "origin/main"),
                     ("--type", "claim", "--symbols-from", "origin/main", "--delta"),
                     ("--type", "claim", "--lane", "lane/x", "--delta")):
            rc, sent, _ = self._run(mail, monkeypatch, tmp_path, [], *args)
            assert rc == 1 and sent == [], args
        assert capsys.readouterr().err.count("mail: refused") == 3


class TestRefresh:
    """`refresh`, the worker tick's one call: the lane is the branch checked out here (never
    typed), the base the ship driver's default, and the send a `--delta` claim, so a tick writes
    only what the lane's diff adds. Every way there is nothing to do prints a line and exits 0
    (a worker stops on anything not green); a write that fails exits 1."""

    PLACEMENTS = TestSymbolsFromTheLane.PLACEMENTS

    def _run(self, mail, monkeypatch, tmp_path, own, branch="lane/x", *args: str, base=None):
        sent: list[dict] = []
        bases: list[str] = []
        reads: list[str] = []   # each read of the ship driver's base, by the remedy it was given

        def lane(root, base, **kw):
            bases.append(base)
            return {k: dict(v, symbols=set(v["symbols"])) for k, v in self.PLACEMENTS.items()}

        def default_base(**kw):
            reads.append(kw.get("remedy", ""))
            return "origin/trunk"

        monkeypatch.setattr(mail, "machine_setting", lambda root, **kw: ("mac", "git config espalier.machine = mac"))
        monkeypatch.setattr(mail, "current_branch", lambda root, **kw: branch)
        monkeypatch.setattr(mail, "_ship_default_base", base or default_base)
        monkeypatch.setattr(mail._symbols, "symbols_of_lane", lane)
        monkeypatch.setattr(mail, "read_mail", lambda root, **kw: ({"mac": list(own)}, {}))
        monkeypatch.setattr(mail, "send", lambda root, message, **kw: sent.append(message))
        rc = mail.main(["--root", str(tmp_path), "refresh", *args])
        return rc, sent, bases, reads

    def _claim(self, mail, **kw):
        return _msg(mail, "mac", "claim", "", lane="lane/x", symbols_rule=mail._symbols.RULE, **kw)

    def test_the_lane_is_the_branch_and_the_send_a_delta_against_the_ship_driver_s_base(
            self, mail, monkeypatch, tmp_path):
        """Dies to: the lane read from anything but the branch, a base other than the ship
        driver's default, or the whole lane re-sent (not a delta) on every tick."""
        own = [self._claim(mail, symbols=["tools/cc/mail.py::send"])]
        rc, sent, bases, reads = self._run(mail, monkeypatch, tmp_path, own)
        assert rc == 0 and bases == ["origin/trunk"] and len(reads) == 1, (bases, reads)
        (m,) = sent
        assert m["type"] == "claim" and m["re"]["lane"] == "lane/x", m
        assert m["re"][mail.SYMBOLS_KEY] == ["tools/cc/mail.py::new_message"], m["re"]
        assert m["re"][mail.SYMBOLS_RULE_KEY] == mail._symbols.RULE

    def test_the_lane_is_never_typed(self, mail, monkeypatch, tmp_path, capsys):
        """Dies to: a `--lane` on the verb (the lane spelled by hand, the footgun release_lane records)."""
        with pytest.raises(SystemExit) as stop:
            mail.main(["--root", str(tmp_path), "refresh", "--lane", "lane/x"])
        assert stop.value.code == 2

    @pytest.mark.parametrize("own, said", [
        ([], "has sent no claim on lane/x"),
        (["released"], "no live claim on this lane"),
        (["current"], "no new symbols"),
    ], ids=["never-claimed", "released", "nothing-new"])
    def test_nothing_to_do_says_so_and_exits_zero(self, mail, monkeypatch, tmp_path, capsys, own, said):
        """The three ways a tick has nothing to send. Dies to: any of them exiting 1 (a lane its seat
        never claimed, or one whose claims a push released, would stop the worker on every tick),
        sending anything, or a lane with no live claim reading the base (a `gh` call a tick with
        nothing to add never needs)."""
        claims = []
        if own == ["released"]:
            claims = [self._claim(mail, symbols=["tools/cc/mail.py::send"]),
                      _msg(mail, "mac", "release", "", lane="lane/x")]
        elif own == ["current"]:
            claims = [self._claim(mail, symbols=["tools/cc/mail.py::send", "tools/cc/mail.py::new_message"],
                                  paths=["docs/x.md"])]
        rc, sent, _, reads = self._run(mail, monkeypatch, tmp_path, claims)
        out = capsys.readouterr()
        assert rc == 0 and sent == [] and said in out.out + out.err, (out.out, out.err)
        assert len(reads) == (1 if own == ["current"] else 0), reads

    @pytest.mark.parametrize("branch, said", [("", "HEAD is detached"), ("main", "has sent no claim on main")],
                             ids=["detached", "the-default-branch"])
    def test_no_lane_checked_out_says_so_and_exits_zero(self, mail, monkeypatch, tmp_path, capsys, branch, said):
        """Dies to: a detached HEAD (mid-rebase) or a seat between lanes on the default branch read as
        a refusal, which stops the worker, or as a lane to claim: a claim command spelled with the
        branch in it is, on the default branch, a claim on `main` no push ever releases (failure-mode
        review, driven)."""
        rc, sent, _, _ = self._run(mail, monkeypatch, tmp_path, [], branch)
        out = capsys.readouterr()
        assert rc == 0 and sent == [] and said in out.out + out.err, (out.out, out.err)
        assert "--lane" not in out.out + out.err, out.out

    def test_a_claim_under_a_name_other_than_the_branch_is_named(self, mail, monkeypatch, tmp_path, capsys):
        """A seat that claimed lane/y and works on lane/y-2 is never refreshed, and the other seat's
        board then reads `overlaps: none` over one function both change (failure-mode review,
        driven). Dies to: the line not naming the lanes this machine's live claims are on."""
        own = [_msg(mail, "mac", "claim", "", lane="lane/y", paths=["pkg/a.py"])]
        rc, sent, _, reads = self._run(mail, monkeypatch, tmp_path, own, "lane/y-2")
        out = capsys.readouterr().out
        assert rc == 0 and sent == [] and reads == [], out
        assert "has sent no claim on lane/y-2" in out and "its live claims are on lane/y;" in out, out

    def test_a_base_that_cannot_be_read_skips_the_tick_and_says_why(self, mail, monkeypatch, tmp_path, capsys):
        """`gh` signed out or offline, on a lane with a live claim: each tick reads the base (both
        reviews, driven). Dies to: the tick exiting 1, so every seat stops at once, or the line
        offering `--symbols-from <base>`, send's flag that refresh refuses."""
        class Refused(Exception):
            pass

        def default_branch():
            raise Refused("gh could not name the default branch: sign in (gh auth status) or fix the remote")

        monkeypatch.setitem(sys.modules, "_mail_ship", type(sys)("_mail_ship"))
        sys.modules["_mail_ship"].Refused, sys.modules["_mail_ship"].default_branch = Refused, default_branch
        own = [self._claim(mail, symbols=["tools/cc/mail.py::send"])]
        rc, sent, bases, _ = self._run(mail, monkeypatch, tmp_path, own, base=mail._ship_default_base)
        out = capsys.readouterr()
        assert rc == 0 and sent == [] and bases == [], (out.out, out.err)
        assert "the base could not be read" in out.out and "the next tick" in out.out, out.out
        assert "sign in (gh auth status)" in out.out and "--lane=lane/x --delta" in out.out, out.out
        assert "(--symbols-from <base>)" not in out.out, out.out

    def test_a_branch_named_past_ascii_is_escaped_in_the_line(self, mail, monkeypatch, tmp_path, capsys):
        """Dies to: the branch echoed raw (operator text is 7-bit ASCII here: a redirected Windows
        stdout stops on the first letter past it; code review, driven)."""
        own = [_msg(mail, "mac", "claim", "", lane="lane/café-2", paths=["a.py"])]
        rc, _sent, _, _ = self._run(mail, monkeypatch, tmp_path, own, "lane/café")
        out = capsys.readouterr().out
        assert rc == 0 and out.isascii() and "lane/caf\\xe9" in out and "lane/caf\\xe9-2" in out, out

    def test_a_branch_spelled_like_an_option_is_the_lane(self, mail, monkeypatch, tmp_path):
        """Dies to: the lane handed to the send as an argument of its own, which argparse reads as an
        option (a branch `-z` stopped the send with its usage, code review driven)."""
        own = [_msg(mail, "mac", "claim", "", lane="-z", symbols_rule=mail._symbols.RULE,
                    symbols=["tools/cc/mail.py::send"])]
        rc, sent, _, _ = self._run(mail, monkeypatch, tmp_path, own, "-z")
        assert rc == 0 and [m["re"]["lane"] for m in sent] == ["-z"], sent

    def test_a_dry_run_prints_the_line_and_sends_nothing(self, mail, monkeypatch, tmp_path, capsys):
        own = [self._claim(mail, symbols=["tools/cc/mail.py::send"])]
        rc, sent, _, _ = self._run(mail, monkeypatch, tmp_path, own, "lane/x", "--dry-run")
        assert rc == 0 and sent == [] and '"lane":"lane/x"' in capsys.readouterr().out

    def test_a_lane_is_refreshed_on_real_git_from_outside_its_checkout(self, mail, machines, monkeypatch,
                                                                       tmp_path, capsys):
        """End to end on real git: a lane branch, its first claim by hand, an edit, two ticks run from
        a directory outside the checkout, then a detached HEAD. Dies to: `--root` lost on the way to
        the send (the cwd answers instead), the lane read some way other than `branch
        --show-current` (a detached HEAD read as a lane named HEAD), or a tick sending again what the
        lane's claims hold (code review, driven)."""
        mac, origin = machines["mac"], machines["origin"]
        _git(mac, "switch", "--quiet", "-c", "lane/r")
        (mac / "pkg").mkdir()
        (mac / "pkg" / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        _git(mac, "add", "pkg/a.py")
        _git(mac, "commit", "--quiet", "-m", "f")
        monkeypatch.setattr(mail, "_ship_default_base", lambda **kw: "origin/main")
        monkeypatch.chdir(tmp_path)
        root = ["--root", str(mac)]
        assert mail.main([*root, "send", "--type", "claim", "--lane", "lane/r", "--symbols-from",
                          "--text", "the first claim, by hand"]) == 0
        (mac / "pkg" / "a.py").write_text("def f():\n    return 1\n\n\ndef g():\n    return 2\n", encoding="utf-8")
        assert mail.main([*root, "refresh"]) == 0
        assert mail.main([*root, "refresh"]) == 0
        claims = [json.loads(x) for x in _origin_file(origin, "mac").splitlines()]
        assert len(claims) == 2, claims
        assert "pkg/a.py::g" not in claims[0]["re"].get(mail.SYMBOLS_KEY, []), claims[0]
        assert "pkg/a.py::g" in claims[1]["re"].get(mail.SYMBOLS_KEY, []), claims[1]
        assert capsys.readouterr().out.rstrip().endswith("no new symbols")
        _git(mac, "switch", "--quiet", "--detach")
        assert mail.main([*root, "refresh"]) == 0
        assert "HEAD is detached" in capsys.readouterr().out


class TestAWriteRacingTheSeatsOwn:
    """The seat's ref moves by compare-and-swap, so a refresh racing the seat's own claim is
    refused, says it raced, and loses nothing: the next tick sends it (driven on real git)."""

    def test_two_sends_back_to_back_both_land(self, mail, machines):
        mac, origin = machines["mac"], machines["origin"]
        for text in ("one", "two"):
            mail.send(mac, _msg(mail, "mac", "note", text), run=_real_run(mail), say=lambda _s: None)
        assert [json.loads(x)["text"] for x in _origin_file(origin, "mac").splitlines()] == ["one", "two"]

    def test_a_write_racing_another_is_refused_as_a_race_and_loses_nothing(self, mail, machines):
        """Dies to: the ref moved without its compare-and-swap (the racing write overwritten), or the
        refusal not saying it raced (a worker reads a generic git failure as one to stop on)."""
        mac, origin = machines["mac"], machines["origin"]
        real = _real_run(mail)
        racer = _msg(mail, "mac", "claim", "the seat's own", lane="lane/x", paths=["a.py"])
        raced = []

        def run(argv, **kw):
            if argv[:2] == ["git", "update-ref"] and not raced:
                raced.append(True)   # the seat's own claim lands between this write's read and its swap
                mail.send(mac, racer, run=real, say=lambda _s: None)
            return real(argv, **kw)

        refresh = _msg(mail, "mac", "claim", "the refresh", lane="lane/x", paths=["b.py"])
        with pytest.raises(mail.Unresolvable, match="moved under this send"):
            mail.send(mac, refresh, run=run, say=lambda _s: None)
        assert [json.loads(x)["id"] for x in _origin_file(origin, "mac").splitlines()] == [racer["id"]]
        mail.send(mac, refresh, run=real, say=lambda _s: None)   # the next tick
        assert [json.loads(x)["id"] for x in _origin_file(origin, "mac").splitlines()] == [racer["id"], refresh["id"]]

    def test_a_write_that_moved_the_ref_and_has_not_pushed_is_a_race(self, mail, machines):
        """The racing write moved this checkout's ref and is still pushing. Dies to: the tip re-read
        on the remote-tracking ref, which only a push or a fetch moves, so the race reads as git's
        own refusal (code review, driven by mutation)."""
        mac = machines["mac"]
        real = _real_run(mail)
        mail.send(mac, _msg(mail, "mac", "note", "one"), run=real, say=lambda _s: None)
        ref = "refs/heads/mail/mac"
        moved: list[str] = []

        def run(argv, **kw):
            if argv[:2] == ["git", "update-ref"] and not moved:
                tip = real(["git", "rev-parse", ref], cwd=str(mac))[1].strip()
                moved.append(mail._commit_blob(mac, "{}\n", tip, "the racing write", run=real))
                assert real(["git", "update-ref", ref, moved[0], tip], cwd=str(mac))[0] == 0
            return real(argv, **kw)

        with pytest.raises(mail.Unresolvable, match="moved under this send"):
            mail.send(mac, _msg(mail, "mac", "note", "two"), run=run, say=lambda _s: None)

    def test_a_lock_left_behind_is_git_s_refusal_not_a_race(self, mail, machines):
        """A stale `<ref>.lock` (a write killed mid-swap) fails every update-ref and moves nothing.
        Dies to: the tip check dropped, so every failure reads as a race and the seat is told the
        next tick sends it, on every tick from then on (code review, driven by mutation)."""
        mac = machines["mac"]
        lock = mac / ".git" / "refs" / "heads" / "mail" / "mac.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("", encoding="utf-8")
        with pytest.raises(mail.Unresolvable) as refused:
            mail.send(mac, _msg(mail, "mac", "note", "one"), run=_real_run(mail), say=lambda _s: None)
        assert "update-ref" in str(refused.value) and "moved under" not in str(refused.value), refused.value

    def test_a_swap_that_landed_before_its_run_failed_is_not_a_race(self, mail, machines):
        """update-ref moved the ref and its run then failed (a timeout's kill after the write). Dies
        to: the ref at this write's own commit read as another write's (code review)."""
        mac = machines["mac"]
        real = _real_run(mail)

        def run(argv, **kw):
            got = real(argv, **kw)
            if argv[:2] == ["git", "update-ref"] and len(argv) == 5:
                return 1, "", "the run was cut short"
            return got

        with pytest.raises(mail.Unresolvable) as refused:
            mail.send(mac, _msg(mail, "mac", "note", "one"), run=run, say=lambda _s: None)
        assert "moved under" not in str(refused.value), refused.value

    def test_a_send_is_read_back_where_the_fetch_refspec_misses_the_mail(self, mail, machines):
        """A clone that fetches only its branch has no remote-tracking ref a push moves, so a refresh
        read this machine's claims one send behind and the next tick sent the same symbols again
        (code review, driven on a single-branch clone). Dies to: the remote-tracking ref left where
        the push found it."""
        mac = machines["mac"]
        _git(mac, "config", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/main")
        m = _msg(mail, "mac", "claim", "one", lane="lane/x", paths=["a.py"])
        mail.send(mac, m, run=_real_run(mail), say=lambda _s: None)
        by_machine, _skipped = mail.read_mail(mac, run=_real_run(mail))
        assert [x["id"] for x in by_machine.get("mac", [])] == [m["id"]], by_machine


@pytest.mark.skipif(not __import__("shutil").which("git"), reason="git is the oracle for per-worktree config")
class TestInheritedWorktreeName:
    """A linked worktree reads its clone's config, so without a `--worktree`
    name it answers the main checkout's name: an assign from it would read as
    the dispatcher's. Driven on real git, since git's own config scoping is the
    thing under test."""

    def _git(self, *args, cwd):
        subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, env=_git_env())

    def test_an_inherited_name_is_refused_and_an_own_name_is_not(self, mail, tmp_path):
        """Dies to: the check reading the shared config instead of the
        worktree's own."""
        repo = tmp_path / "repo"
        repo.mkdir()
        self._git("init", "-q", cwd=repo)
        self._git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base", cwd=repo)
        self._git("config", "espalier.machine", "air", cwd=repo)
        self._git("worktree", "add", "-q", str(tmp_path / "wt"), cwd=repo)
        assert mail.worktree_name_inherited(repo) is False                 # the main checkout
        assert mail.worktree_name_inherited(tmp_path / "wt") is True       # inherits "air"
        refusal = mail.assign_refusal(tmp_path / "wt", "air")
        assert refusal and "answers the clone's shared name 'air'" in refusal
        self._git("config", "extensions.worktreeConfig", "true", cwd=repo)
        assert mail.worktree_name_inherited(tmp_path / "wt") is True       # the switch alone names nothing
        self._git("config", "--worktree", "espalier.machine", "air-2", cwd=tmp_path / "wt")
        assert mail.worktree_name_inherited(tmp_path / "wt") is False

    def test_the_switch_is_read_where_git_reads_it(self, mail, tmp_path, monkeypatch):
        """git honours extensions.worktreeConfig in the repository's own
        config only, and reads it as a boolean. Dies to the switch read with
        a plain --get: a global `true` made --worktree exit 128 on a clone of
        several worktrees, read as a failed read, so a worktree that shares its
        clone's name minted and assigned as the clone; and to `yes` read as off."""
        glob = tmp_path / "global.gitconfig"
        glob.write_text("[extensions]\n\tworktreeConfig = true\n", encoding="utf-8")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(glob))
        repo = tmp_path / "repo"
        repo.mkdir()
        self._git("init", "-q", cwd=repo)
        self._git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base", cwd=repo)
        self._git("config", "espalier.machine", "air", cwd=repo)
        self._git("worktree", "add", "-q", str(tmp_path / "wt"), cwd=repo)
        self._git("worktree", "add", "-q", str(tmp_path / "wt2"), cwd=repo)
        name, how = mail.machine_setting(tmp_path / "wt", scope="worktree")
        assert name is None and not how.startswith(mail.MACHINE_UNREAD), how
        assert mail.worktree_name_inherited(tmp_path / "wt") is True
        refusal = mail.assign_refusal(tmp_path / "wt", "air") or ""
        assert "answers the clone's shared name 'air'" in refusal, refusal
        self._git("config", "extensions.worktreeConfig", "yes", cwd=repo)
        self._git("config", "--worktree", "espalier.machine", "air-wt", cwd=tmp_path / "wt")
        assert mail.machine_setting(tmp_path / "wt", scope="worktree")[0] == "air-wt"
        assert mail.worktree_name_inherited(tmp_path / "wt") is False


@pytest.mark.skipif(not __import__("shutil").which("git"), reason="git is the oracle for per-worktree config")
class TestNameThisWorktree:
    """SessionStart gives a linked worktree of a named clone its own name
    (TP-479 Wave B-2): ``<clone>-<worktree directory>``, set with
    ``--worktree`` scope, read back, once. Driven on real git, since git's own
    config scoping is the thing under test."""

    def _git(self, *args, cwd):
        return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=_git_env()).stdout.strip()

    def _clone(self, tmp_path, name="win"):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._git("init", "-q", cwd=repo)
        self._git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base", cwd=repo)
        if name:
            self._git("config", "espalier.machine", name, cwd=repo)
        return repo

    def test_a_worktree_is_named_once_and_the_clone_keeps_its_name(self, mail, tmp_path):
        """Dies to: the name set without --worktree scope, which renames the
        clone itself."""
        repo = self._clone(tmp_path)
        self._git("worktree", "add", "-q", str(tmp_path / "Feature_X"), cwd=repo)
        wt = tmp_path / "Feature_X"
        name, said = mail.name_this_worktree(wt)
        assert name == "win-feature-x"
        assert "named this worktree win-feature-x" in said and "[id_blocks]" in said
        assert self._git("config", "--worktree", "--get", "espalier.machine", cwd=wt) == "win-feature-x"
        assert self._git("config", "--get", "espalier.machine", cwd=repo) == "win"
        assert mail.worktree_name_inherited(wt) is False
        assert mail.name_this_worktree(wt) == (None, ""), "a named worktree is left alone"

    def test_the_main_checkout_and_an_unnamed_clone_are_left_alone(self, mail, tmp_path):
        repo = self._clone(tmp_path, name=None)
        self._git("worktree", "add", "-q", str(tmp_path / "wt"), cwd=repo)
        assert mail.name_this_worktree(repo) == (None, "")
        assert mail.name_this_worktree(tmp_path / "wt") == (None, ""), "the channel is off: nothing to name"
        assert mail.worktree_name_inherited(tmp_path / "wt") is True

    def test_a_derived_name_another_worktree_answers_is_refused(self, mail, tmp_path):
        repo = self._clone(tmp_path)
        self._git("worktree", "add", "-q", str(tmp_path / "one"), cwd=repo)
        self._git("config", "extensions.worktreeConfig", "true", cwd=repo)
        self._git("config", "--worktree", "espalier.machine", "win-two", cwd=tmp_path / "one")
        self._git("worktree", "add", "-q", str(tmp_path / "two"), cwd=repo)
        name, said = mail.name_this_worktree(tmp_path / "two")
        assert name is None and "`win-two`, is taken by" in said
        assert "git config --worktree espalier.machine <name>" in said
        assert mail.worktree_name_inherited(tmp_path / "two") is True

    def test_the_clone_name_reads_past_a_worktree_name(self, mail, tmp_path):
        """``clone_machine`` reads the shared config even in a named worktree:
        a worktree seat mints from its clone's block by it."""
        repo = self._clone(tmp_path)
        self._git("worktree", "add", "-q", str(tmp_path / "feat"), cwd=repo)
        assert mail.name_this_worktree(tmp_path / "feat")[0] == "win-feat"
        assert mail.clone_machine(tmp_path / "feat")[0] == "win"
        assert mail.machine_setting(tmp_path / "feat")[0] == "win-feat"

    def test_a_separate_git_dir_clone_is_left_alone(self, mail, tmp_path):
        """Its .git is a file too; nothing is renamed (git-dir equals common-dir)."""
        repo = tmp_path / "repo"
        self._git("init", "-q", f"--separate-git-dir={tmp_path / 'repo.git'}", str(repo), cwd=tmp_path)
        self._git("config", "espalier.machine", "win", cwd=repo)
        assert (repo / ".git").is_file()
        assert mail.name_this_worktree(repo) == (None, "")
        assert self._git("config", "--get", "espalier.machine", cwd=repo) == "win"

    def test_a_worktree_whose_directory_is_gone_does_not_stop_the_naming(self, mail, tmp_path):
        import shutil
        repo = self._clone(tmp_path)
        self._git("worktree", "add", "-q", str(tmp_path / "gone"), cwd=repo)
        shutil.rmtree(tmp_path / "gone")                     # a prunable entry is left behind
        self._git("worktree", "add", "-q", str(tmp_path / "here"), cwd=repo)
        assert mail.name_this_worktree(tmp_path / "here")[0] == "win-here"

    def test_the_derived_name_fits_the_machine_grammar(self, mail):
        assert mail.worktree_seat_name("win", "Feature_X") == "win-feature-x"
        long = mail.worktree_seat_name("win", "a-very-long-worktree-name-from-a-branch-slug")
        assert long and len(long) <= 32 and mail._MACHINE_RE.match(long) and not long.endswith("-")
        assert mail.worktree_seat_name("win", "___") is None


class TestCursor:
    def test_the_cursor_round_trips_and_is_lf_json(self, mail, tmp_path):
        mail.write_cursor(tmp_path, {"win": "id-1"})
        assert mail.read_cursor(tmp_path) == {"win": "id-1"}
        raw = (tmp_path / mail.CURSOR).read_bytes()
        assert b"\r" not in raw and raw.endswith(b"\n")
        assert list((tmp_path / ".espalier-state").iterdir()) == [tmp_path / mail.CURSOR]  # one file, no sibling

    def test_an_absent_or_broken_cursor_reads_as_nothing_seen(self, mail, tmp_path):
        assert mail.read_cursor(tmp_path) == {}
        (tmp_path / ".espalier-state").mkdir()
        (tmp_path / mail.CURSOR).write_text("{not json", encoding="utf-8")
        assert mail.read_cursor(tmp_path) == {}

    def test_unread_is_everything_after_the_cursor_from_other_machines_only(self, mail):
        m1 = _msg(mail, "win", "note", "one", now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        m2 = _msg(mail, "win", "note", "two", now=datetime(2026, 1, 2, tzinfo=timezone.utc))
        mine = _msg(mail, "mac", "note", "mine")
        by = {"win": [m1, m2], "mac": [mine]}
        assert [m["id"] for m in mail.unread(by, {}, exclude_machine="mac")] == [m1["id"], m2["id"]]
        assert [m["id"] for m in mail.unread(by, {"win": m1["id"]}, exclude_machine="mac")] == [m2["id"]]
        assert mail.unread(by, {"win": m2["id"]}, exclude_machine="mac") == []
        assert mail.advance_cursor({}, by, exclude_machine="mac") == {"win": m2["id"]}

    def test_a_cursor_whose_message_is_gone_hides_what_was_stamped_before_it(self, mail):
        """A ref pruned or rebuilt by a hand drops the message the cursor
        names; ids open with their stamp, so what is stamped after it is
        unread and nothing before it floods back."""
        m1 = _msg(mail, "win", "note", "one", now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        gone = _msg(mail, "win", "note", "gone", now=datetime(2026, 1, 2, tzinfo=timezone.utc))
        m3 = _msg(mail, "win", "note", "three", now=datetime(2026, 1, 3, tzinfo=timezone.utc))
        by = {"win": [m1, m3]}
        assert [m["id"] for m in mail.unread(by, {"win": gone["id"]}, exclude_machine="mac")] == [m3["id"]]


# ── the guard ────────────────────────────────────────────────────────────────

class TestSecretGuard:
    def test_the_guards_own_matcher_is_loaded_by_path_under_a_private_alias(self, mail):
        matcher = mail._secret_matcher()
        assert callable(matcher) and "_mail_write_guard" in sys.modules
        assert "write_guard" not in sys.modules or sys.modules["write_guard"] is not sys.modules["_mail_write_guard"]

    def test_a_secret_path_in_the_text_or_the_paths_is_named(self, mail):
        m = _msg(mail, "mac", "note", "read the .env and secrets/key.txt then stop", paths=["config/.env.production"])
        hits = mail.secret_hits(m)
        assert len(hits) == 3 and hits[0].startswith("`.env` (") and "`config/.env.production` (" in hits[2]

    def test_benign_text_and_paths_pass(self, mail):
        m = _msg(mail, "mac", "note", "no secrets here, the environment is fine", paths=["docs/ENV.md", ".env.example"])
        assert mail.secret_hits(m) == []


# ── orchestration on a recording fake ────────────────────────────────────────

class _Fake:
    """argv-prefix -> answer; every call recorded; an undescribed spawn fails."""

    def __init__(self, answers: dict[tuple[str, ...], tuple[int, str, str]]):
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kw):
        argv = list(argv)
        self.calls.append(argv)
        best = None
        for key in self.answers:
            if tuple(argv[: len(key)]) == key and (best is None or len(key) > len(best)):
                best = key
        if best is None:
            raise AssertionError("unplanned spawn: " + " ".join(argv))
        return self.answers[best]

    def has(self, *prefix: str) -> bool:
        return any(tuple(c[: len(prefix)]) == prefix for c in self.calls)


class TestSendRefusals:
    def test_no_machine_name_refuses_before_any_network_call(self, mail, tmp_path):
        fake = _Fake({("git", "config", "--get", "espalier.machine"): (1, "", "")})
        with pytest.raises(mail.Unresolvable, match=r"not set.*git config espalier\.machine"):
            mail.send(tmp_path, _msg(mail, "mac", "note", "x"), run=fake)
        assert not fake.has("git", "ls-remote") and not fake.has("git", "push")

    def test_a_malformed_name_reads_as_off_and_says_so(self, mail, tmp_path):
        fake = _Fake({("git", "config", "--get", "espalier.machine"): (0, "Mac Book\n", "")})
        machine, how = mail.machine_setting(tmp_path, run=fake)
        assert machine is None and "not a name this channel takes" in how

    def test_a_message_from_another_name_is_refused(self, mail, tmp_path):
        fake = _Fake({("git", "config", "--get", "espalier.machine"): (0, "mac\n", "")})
        with pytest.raises(mail.Unresolvable, match="from 'win', this box is 'mac'"):
            mail.send(tmp_path, _msg(mail, "win", "note", "x"), run=fake)

    def test_a_secret_path_refuses_before_any_network_call(self, mail, tmp_path):
        fake = _Fake({("git", "config", "--get", "espalier.machine"): (0, "mac\n", "")})
        with pytest.raises(mail.Unresolvable, match=r"public origin.*`\.env`"):
            mail.send(tmp_path, _msg(mail, "mac", "note", "cat .env please"), run=fake)
        assert not fake.has("git", "ls-remote")

    def test_a_local_ref_not_behind_origins_is_refused_as_a_second_writer(self, mail, tmp_path):
        fake = _Fake({
            ("git", "config", "--get", "espalier.machine"): (0, "mac\n", ""),
            ("git", "ls-remote", "--heads", "origin", "refs/heads/mail/mac"): (0, "bbbb\trefs/heads/mail/mac\n", ""),
            ("git", "rev-parse", "-q", "--verify"): (0, "aaaa\n", ""),
            ("git", "fetch", "--quiet", "origin"): (0, "", ""),
            ("git", "merge-base", "--is-ancestor", "aaaa", "bbbb"): (1, "", ""),
        })
        with pytest.raises(mail.Unresolvable, match="one writer per machine"):
            mail.send(tmp_path, _msg(mail, "mac", "note", "x"), run=fake)
        assert not fake.has("git", "push") and not fake.has("git", "update-ref")

    def test_fetch_mail_never_raises_and_names_the_problem(self, mail, tmp_path):
        fake = _Fake({("git", "fetch"): (128, "", "fatal: could not read from remote repository\n")})
        ok, problem = mail.fetch_mail(tmp_path, run=fake)
        assert ok is False and "could not read from remote" in problem

    def test_a_parent_whose_file_cannot_be_read_refuses_and_builds_nothing(self, mail, tmp_path):
        """Code review, 2026-10-05: the one read that collapsed "cannot read
        the parent's file" into "no prior mail" would have built a tip that
        dropped every earlier message on a partial fetch."""
        fake = _Fake({
            ("git", "config", "--get", "espalier.machine"): (0, "mac\n", ""),
            ("git", "ls-remote", "--heads", "origin", "refs/heads/mail/mac"): (0, "bbbb\trefs/heads/mail/mac\n", ""),
            ("git", "rev-parse", "-q", "--verify"): (1, "", ""),
            ("git", "fetch", "--quiet", "origin"): (0, "", ""),
            ("git", "show", "bbbb:mail.jsonl"): (128, "", "fatal: path 'mail.jsonl' does not exist in 'bbbb'"),
        })
        with pytest.raises(mail.Unresolvable, match=r"git show bbbb:mail\.jsonl failed: fatal: path"):
            mail.send(tmp_path, _msg(mail, "mac", "note", "x"), run=fake)
        assert not fake.has("git", "hash-object") and not fake.has("git", "push")

    def test_every_git_call_runs_under_the_stripped_env(self, mail, tmp_path):
        """`git_env()` strips the repo-selecting overrides and sets
        GIT_TERMINAL_PROMPT=0; the root question was the one call without it
        (failure-mode review, 2026-10-05)."""
        envs: list[dict | None] = []

        def spy(argv, **kw):
            envs.append(kw.get("env"))
            return 0, str(tmp_path) + "\n", ""

        mail.run, real = spy, mail.run
        try:
            mail._repo_root(None)
        finally:
            mail.run = real
        assert envs and all(env is not None and env.get("GIT_TERMINAL_PROMPT") == "0" for env in envs)


# ── real git: the machines ───────────────────────────────────────────────────

def _git(repo: Path, *args: str, check: bool = True, input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=_git_env(), check=check, timeout=45, input=input)


def _identity(repo: Path, name: str) -> None:
    _git(repo, "config", "user.name", name)
    _git(repo, "config", "user.email", f"{name}@example.invalid")
    _git(repo, "config", "commit.gpgsign", "false")


def _name(repo: Path, machine: str) -> None:
    _git(repo, "config", "espalier.machine", machine)


@pytest.fixture
def machines(tmp_path):
    """A bare origin and two named clones. A third, nameless clone is a
    helper for the same-name case."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "--quiet", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "--quiet", str(origin), str(seed))
    _identity(seed, "seed")
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "--quiet", "-m", "seed")
    _git(seed, "push", "--quiet", "-u", "origin", "main")
    clones = {"origin": origin}
    for name in ("mac", "win"):
        clone = tmp_path / name
        _git(tmp_path, "clone", "--quiet", str(origin), str(clone))
        _identity(clone, name)
        _name(clone, name)
        clones[name] = clone
    return clones


def _real_run(mail):
    def run(argv, **kw):
        kw.setdefault("env", mail.git_env())
        return mail.run(argv, **kw)
    return run


def _origin_file(origin: Path, machine: str) -> str:
    return _git(origin, "show", f"refs/heads/mail/{machine}:mail.jsonl").stdout


class TestTwoMachines:
    def test_a_send_lands_on_origin_and_touches_nothing_in_the_worktree(self, mail, machines):
        mac, origin = machines["mac"], machines["origin"]
        head = _git(mac, "rev-parse", "HEAD").stdout
        m = _msg(mail, "mac", "claim", "the ledger areas", lane="lane/x", paths=["tools/cc/ledger_row.py"])
        said: list[str] = []
        commit = mail.send(mac, m, run=_real_run(mail), say=said.append)
        assert _git(origin, "rev-parse", "refs/heads/mail/mac").stdout.strip() == commit
        lines = _origin_file(origin, "mac").splitlines()
        assert len(lines) == 1 and json.loads(lines[0])["id"] == m["id"]
        assert _git(mac, "rev-parse", "HEAD").stdout == head
        assert _git(mac, "status", "--porcelain").stdout == ""
        assert _git(mac, "diff", "--cached", "--name-only").stdout == ""
        assert not (mac / "mail.jsonl").exists()
        assert _git(mac, "cat-file", "-p", f"{commit}^{{tree}}").stdout.count("\n") == 1  # one file in the tree
        assert said == [f"sent claim {m['id']} as {commit[:7]} on refs/heads/mail/mac"]

    def test_the_other_machine_fetches_reads_and_sees_the_headline(self, mail, machines):
        mac, win = machines["mac"], machines["win"]
        m = _msg(mail, "mac", "request", "please look at the fixture hang", lane="lane/x", paths=["tests/a.py"])
        mail.send(mac, m, run=_real_run(mail), say=lambda _s: None)
        ok, problem = mail.fetch_mail(win, run=_real_run(mail))
        assert ok, problem
        by_machine, skipped = mail.read_mail(win, run=_real_run(mail))
        assert skipped == {} and list(by_machine) == ["mac"]
        assert mail.headline(by_machine["mac"][0]) == 'mac: request re lane/x (1 path) -- "please look at the fixture hang"'
        assert [x["id"] for x in mail.unread(by_machine, mail.read_cursor(win), exclude_machine="win")] == [m["id"]]

    def test_sends_append_one_line_each_and_each_reads_origin_fresh(self, mail, machines):
        mac, origin = machines["mac"], machines["origin"]
        first = _msg(mail, "mac", "note", "one")
        second = _msg(mail, "mac", "note", "two")
        mail.send(mac, first, run=_real_run(mail), say=lambda _s: None)
        mail.send(mac, second, run=_real_run(mail), say=lambda _s: None)
        raw = subprocess.run(["git", "cat-file", "-p", "refs/heads/mail/mac:mail.jsonl"], cwd=origin,
                             capture_output=True, env=_git_env(), check=True, timeout=45).stdout  # BYTES, no pipe re-lining
        assert b"\r" not in raw and raw.endswith(b"\n") and raw.isascii()  # the blob itself is LF on every host
        messages, skipped = mail.decode_lines(raw.decode("ascii"))
        assert skipped == 0 and [x["text"] for x in messages] == ["one", "two"]
        assert _git(origin, "rev-list", "--count", "refs/heads/mail/mac").stdout.strip() == "2"

    def test_a_release_closes_the_claim_for_every_reader(self, mail, machines):
        mac, win = machines["mac"], machines["win"]
        claim = _msg(mail, "mac", "claim", "", lane="lane/x", paths=["tools/cc/"])
        mail.send(mac, claim, run=_real_run(mail), say=lambda _s: None)
        mail.fetch_mail(win, run=_real_run(mail))
        assert [c["id"] for c in mail.live_claims(mail.read_mail(win, run=_real_run(mail))[0])] == [claim["id"]]
        mail.send(mac, _msg(mail, "mac", "release", "", ack=claim["id"]), run=_real_run(mail), say=lambda _s: None)
        mail.fetch_mail(win, run=_real_run(mail))
        assert mail.live_claims(mail.read_mail(win, run=_real_run(mail))[0]) == []

    def test_a_second_checkout_under_the_same_name_is_refused_not_overwritten(self, mail, machines, tmp_path):
        """One writer per machine. A re-clone of the same box adopts origin's
        ref (its local one is absent); a checkout whose local ref is NOT behind
        origin's -- origin's history moved under it -- refuses by name, and
        origin keeps what it had."""
        mac, origin = machines["mac"], machines["origin"]
        mail.send(mac, _msg(mail, "mac", "note", "one"), run=_real_run(mail), say=lambda _s: None)
        other = tmp_path / "mac-again"
        _git(tmp_path, "clone", "--quiet", str(origin), str(other))
        _identity(other, "mac-again")
        _name(other, "mac")
        mail.send(other, _msg(mail, "mac", "note", "from the re-clone"), run=_real_run(mail), say=lambda _s: None)
        assert _git(origin, "rev-list", "--count", "refs/heads/mail/mac").stdout.strip() == "2"
        # Now origin's ref is moved to an unrelated history by a hand.
        _git(origin, "update-ref", "refs/heads/mail/mac", _git(origin, "rev-parse", "main").stdout.strip())
        before = _git(origin, "rev-parse", "refs/heads/mail/mac").stdout
        with pytest.raises(mail.Unresolvable, match="one writer per machine"):
            mail.send(mac, _msg(mail, "mac", "note", "three"), run=_real_run(mail), say=lambda _s: None)
        assert _git(origin, "rev-parse", "refs/heads/mail/mac").stdout == before

    def test_a_local_ref_behind_origins_is_adopted_and_the_send_fast_forwards(self, mail, machines, tmp_path):
        """The middle branch of the ref algebra (code review, 2026-10-05): the
        local ref exists and is strictly behind origin's -- a re-clone of the
        same box sent in between -- so origin's tip is the parent and the push
        is a fast-forward that keeps every earlier message."""
        mac, origin = machines["mac"], machines["origin"]
        mail.send(mac, _msg(mail, "mac", "note", "one"), run=_real_run(mail), say=lambda _s: None)
        stale_local = _git(mac, "rev-parse", "refs/heads/mail/mac").stdout.strip()
        other = tmp_path / "mac-again"
        _git(tmp_path, "clone", "--quiet", str(origin), str(other))
        _identity(other, "mac-again")
        _name(other, "mac")
        mail.send(other, _msg(mail, "mac", "note", "two"), run=_real_run(mail), say=lambda _s: None)
        remote_tip = _git(origin, "rev-parse", "refs/heads/mail/mac").stdout.strip()
        assert stale_local != remote_tip
        commit = mail.send(mac, _msg(mail, "mac", "note", "three"), run=_real_run(mail), say=lambda _s: None)
        assert _git(mac, "rev-parse", f"{commit}^").stdout.strip() == remote_tip
        assert _git(origin, "rev-parse", "refs/heads/mail/mac").stdout.strip() == commit
        messages, skipped = mail.decode_lines(_origin_file(origin, "mac"))
        assert skipped == 0 and [x["text"] for x in messages] == ["one", "two", "three"]

    def test_local_mail_machines_names_what_this_clone_already_holds(self, mail, machines):
        mac, win = machines["mac"], machines["win"]
        assert mail.local_mail_machines(win, run=_real_run(mail)) == []
        mail.send(mac, _msg(mail, "mac", "note", "x"), run=_real_run(mail), say=lambda _s: None)
        _git(win, "fetch", "--quiet", "origin")  # a plain fetch, no channel verb, brings the ref in
        assert mail.local_mail_machines(win, run=_real_run(mail)) == ["mac"]

    @pytest.mark.skipif(sys.platform == "win32", reason="a shell pre-receive hook on the bare origin needs sh")
    def test_a_push_origin_refuses_is_rolled_back_so_the_next_send_starts_clean(self, mail, machines):
        mac, origin = machines["mac"], machines["origin"]
        from tests._stubs import write_stub
        hook = write_stub(origin / "hooks" / "pre-receive", "#!/bin/sh\necho 'no mail today' >&2\nexit 1\n")
        with pytest.raises(mail.Unresolvable, match="refused the push.*no mail today"):
            mail.send(mac, _msg(mail, "mac", "note", "x"), run=_real_run(mail), say=lambda _s: None)
        assert _git(mac, "rev-parse", "-q", "--verify", "refs/heads/mail/mac", check=False).returncode != 0
        assert _git(origin, "rev-parse", "-q", "--verify", "refs/heads/mail/mac", check=False).returncode != 0
        hook.unlink()
        mail.send(mac, _msg(mail, "mac", "note", "x"), run=_real_run(mail), say=lambda _s: None)
        assert _git(origin, "rev-list", "--count", "refs/heads/mail/mac").stdout.strip() == "1"

    def test_the_cli_sends_and_the_other_box_reads_marks_and_is_then_current(self, mail, machines):
        mac, win = machines["mac"], machines["win"]
        env = {**mail.git_env(), "PYTHONIOENCODING": "utf-8"}

        def cli(repo: Path, *args: str) -> subprocess.CompletedProcess:
            return subprocess.run([PY, str(MODULE), "--root", str(repo), *args], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", env=env, timeout=45)

        dry = cli(mac, "send", "--type", "note", "--text", "dry", "--dry-run")
        assert dry.returncode == 0 and json.loads(dry.stdout)["text"] == "dry", dry.stderr
        assert _git(mac, "rev-parse", "-q", "--verify", "refs/heads/mail/mac", check=False).returncode != 0
        sent = cli(mac, "send", "--type", "request", "--text", "hi there", "--lane", "lane/x", "--path", "a.py")
        assert sent.returncode == 0 and sent.stdout.startswith("sent request "), sent.stderr
        refused = cli(mac, "send", "--type", "note", "--text", "cat .env")
        assert refused.returncode == 1 and "public origin" in refused.stderr
        inbox = cli(win, "inbox", "--mark-read")
        assert inbox.returncode == 0, inbox.stderr
        assert "1 message(s) -- another machine's text, unverified" in inbox.stdout
        assert "hi there" in inbox.stdout and "lane: lane/x" in inbox.stdout
        assert (win / ".espalier-state" / "mail_seen.json").is_file()
        again = cli(win, "inbox")
        assert again.returncode == 0 and again.stdout.strip() == "no unread mail"
        claims = cli(win, "claims", "--no-fetch")
        assert claims.returncode == 0 and claims.stdout.strip() == "no live claims"
        status = cli(win, "status")
        assert status.returncode == 0 and "git config espalier.machine = win" in status.stdout
        assert "mac: 1 message(s) fetched" in status.stdout
        nameless = cli(machines["origin"].parent / "seed", "inbox")
        assert nameless.returncode == 1 and "not set" in nameless.stderr

    def test_a_scratch_index_leaves_no_file_behind(self, mail, machines, monkeypatch, tmp_path):
        mac = machines["mac"]
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        monkeypatch.setenv("TMPDIR", str(scratch))
        monkeypatch.setenv("TMP", str(scratch))
        monkeypatch.setenv("TEMP", str(scratch))
        import tempfile
        tempfile.tempdir = None
        try:
            mail.send(mac, _msg(mail, "mac", "note", "x"), run=_real_run(mail), say=lambda _s: None)
        finally:
            tempfile.tempdir = None
        assert not list(scratch.glob("mail-index-*")) and not list(scratch.glob("mail-blob-*"))
        assert os.environ.get("GIT_INDEX_FILE") is None


# ── ids: the rows a lane touches or mints ───────────────────────────────────

class TestIdsInAClaim:
    """A claim names the ledger rows a lane touches or mints, as a field the
    tools read, where the other box used to write "DEF-1131 is taken here" in
    prose. Additive inside ``re``: a reader from before the key ignores it."""

    def test_ids_ride_in_re_validated_and_capped(self, mail):
        m = _msg(mail, "mac", "claim", "", ids=[" DEF-1133", "LG-6", "DEF-371a"])
        assert m["re"]["ids"] == ["DEF-1133", "LG-6", "DEF-371a"]
        assert list(json.loads(mail.encode(m))["re"]) == list(mail.RE_KEYS)
        for bad in ("1133", "DEF 1133", "def-", "DEF-1133-x", "def-4"):
            with pytest.raises(mail.Unresolvable, match="not a ledger row id"):
                _msg(mail, "mac", "claim", "", ids=[bad])
        with pytest.raises(mail.Unresolvable, match="the cap is"):
            _msg(mail, "mac", "claim", "", ids=[f"DEF-{n}" for n in range(mail.MAX_IDS + 1)])

    def test_a_claim_may_name_only_ids(self, mail):
        m = _msg(mail, "mac", "claim", "", ids=["DEF-1133"])
        assert m["re"]["lane"] == "" and m["re"]["ids"] == ["DEF-1133"]

    def test_the_headline_counts_ids_beside_paths(self, mail):
        m = _msg(mail, "win", "claim", "", lane="lane/c66", paths=["a.py"], ids=["DEF-1131", "DEF-1132"])
        assert mail.headline(m).startswith("win: claim re lane/c66 (1 path, 2 ids)")

    def test_overlap_on_an_id_is_its_own_hit(self, mail):
        theirs = _msg(mail, "win", "claim", "", lane="lane/c66", classes=["C66"], ids=["DEF-1131", "DEF-1132"])
        found = mail.overlapping_claims([theirs], ids=["DEF-1132"], classes=["C0"], exclude_machine="mac")
        assert [(c["id"], hits) for c, hits in found] == [(theirs["id"], ["id DEF-1132"])]
        assert mail.overlapping_claims([theirs], ids=["DEF-1133"], exclude_machine="mac") == []
        assert mail.overlapping_claims([theirs], ids=["DEF-1132"], exclude_machine="win") == []

    def test_a_message_from_before_the_key_still_reads(self, mail):
        old = '{"v": 1, "id": "x-win-a", "type": "claim", "from": "win", "at": "2026-10-05T00:00:00Z", ' \
              '"re": {"lane": "lane/old", "classes": [], "paths": []}, "text": "", "ack": ""}\n'
        decoded, skipped = mail.decode_lines(old)
        assert skipped == 0
        assert mail.overlapping_claims(decoded, ids=["DEF-1"], lane="lane/old") == [(decoded[0], ["lane lane/old"])]


class TestReleaseLane:
    """The ship driver closes a lane's claims when the lane leaves the
    machine: one release for this machine's live claims on the lane, nothing
    sent when there are none, nothing where the box is unnamed."""

    def test_one_release_closes_the_lanes_claims_and_a_second_sends_nothing(self, mail, machines):
        mac, origin = machines["mac"], machines["origin"]
        run = _real_run(mail)
        a = _msg(mail, "mac", "claim", "", lane="lane/x", ids=["DEF-1133"])
        b = _msg(mail, "mac", "claim", "", lane="lane/x", paths=["tools/cc/mail.py"])
        other = _msg(mail, "mac", "claim", "", lane="lane/y", classes=["C13"])
        for m in (a, b, other):
            mail.send(mac, m, run=run, say=lambda _s: None)
        said: list[str] = []
        commit = mail.release_lane(mac, "lane/x", "shipped", run=run, say=said.append)
        assert commit and said and said[0].startswith("sent release ")
        lines = [json.loads(ln) for ln in _origin_file(origin, "mac").splitlines()]
        assert lines[-1]["type"] == "release" and lines[-1]["re"]["lane"] == "lane/x"
        by_machine, _ = mail.read_mail(mac, run=run)
        assert [c["id"] for c in mail.live_claims(by_machine)] == [other["id"]]
        assert mail.release_lane(mac, "lane/x", run=run, say=said.append) is None
        assert len(said) == 2 and "1 live claim(s) of mac remain on other lanes" in said[1]

    def test_an_unnamed_box_sends_nothing(self, mail, tmp_path):
        fake = _Fake({("git", "config", "--get", "espalier.machine"): (1, "", "")})
        assert mail.release_lane(tmp_path, "lane/x", run=fake) is None
        assert not fake.has("git", "push") and not fake.has("git", "for-each-ref")

    def test_an_unread_name_is_said_and_sends_nothing(self, mail, tmp_path):
        """A name read that failed (a config git cannot parse, a timeout) is not
        an unnamed box: the lane's claims stayed live with no word at the push,
        and every other seat's plan kept warning on them. Dies to: the unread
        reason taken for an unset name."""
        broken = (128, "", "fatal: bad config line 3 in file .git/config")
        fake = _Fake({("git", "config", "--get", "espalier.machine"): broken})
        said: list[str] = []
        assert mail.release_lane(tmp_path, "lane/x", run=fake, say=said.append) is None
        assert len(said) == 1, said
        assert "could not be read" in said[0] and "bad config line 3" in said[0], said[0]
        assert "send --type release --lane lane/x" in said[0] and said[0].isascii()
        assert "turns it on" not in said[0]
        assert not fake.has("git", "push") and not fake.has("git", "for-each-ref")


# ── the records refs: a parked Session Log row, and the fold that brings it in ──
# A handoff whose pull request already merged parks its row on the seat's own
# records ref (one writer per ref, the mail channel's compare-and-swap commit),
# and the next lane's push folds every pending row in and prunes to the cap, the
# one writer of the count. Before this, every lane enforced the cap in its own
# tree and a merged lane's handoff opened a pull request for its row alone
# (seven in two days, #212 to #240).

_ROW_DIR = "memory/session-log.d"


def _row(name: str) -> bytes:
    return f"| {name[:10]} | {name[18:-3]} | the row of {name} |\n".encode("ascii")


def _main_rows(machines, tmp_path, *add: str, prune: tuple[str, ...] = ()) -> None:
    """Land rows on main, and prune some, the way a merged lane does."""
    keeper = tmp_path / "keeper"
    if not keeper.exists():
        _git(tmp_path, "clone", "--quiet", str(machines["origin"]), str(keeper))
        _identity(keeper, "keeper")
    _git(keeper, "pull", "--quiet", "--ff-only", "origin", "main")
    for name in add:
        path = keeper / _ROW_DIR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_row(name))
    for name in prune:
        (keeper / _ROW_DIR / name).unlink()
    _git(keeper, "add", "-A", "--", _ROW_DIR)
    _git(keeper, "commit", "--quiet", "-m", "rows")
    _git(keeper, "push", "--quiet", "origin", "main")


def _park(mail, root: Path, name: str) -> str:
    return mail.park(root, f"{_ROW_DIR}/{name}", _row(name), "origin/main", run=_real_run(mail),
                     say=lambda _s: None)


def _ref_rows(origin: Path, machine: str) -> list[str]:
    return _git(origin, "ls-tree", "-r", "--name-only", f"refs/heads/records/{machine}").stdout.split()


@pytest.fixture(scope="module")
def ship_driver():
    return _load(REPO_ROOT / "tools" / "cc" / "ship.py", "ship_for_the_records_ref")


@pytest.fixture(scope="module")
def fragments():
    """The record loader: the fold's trailer has its one home there."""
    return _load(REPO_ROOT / "tools" / "cc" / "_record_fragments.py", "fragments_for_the_records_ref")


class TestTheRecordsRef:
    def test_a_park_writes_the_row_on_the_seats_records_ref_and_touches_nothing_here(self, mail, machines):
        """Dies to: a park through the working tree or the index, or a ref other
        than the seat's own records ref."""
        mac, origin = machines["mac"], machines["origin"]
        head = _git(mac, "rev-parse", "HEAD").stdout
        name = "2026-10-16-010101-mac.md"
        commit = _park(mail, mac, name)
        assert _git(origin, "rev-parse", "refs/heads/records/mac").stdout.strip() == commit
        assert _ref_rows(origin, "mac") == [f"{_ROW_DIR}/{name}"]
        raw = subprocess.run(["git", "cat-file", "-p", f"refs/heads/records/mac:{_ROW_DIR}/{name}"], cwd=origin,
                             capture_output=True, env=_git_env(), check=True, timeout=45).stdout
        assert raw == _row(name)
        assert _git(mac, "rev-parse", "HEAD").stdout == head
        assert _git(mac, "status", "--porcelain").stdout == ""
        assert _git(mac, "diff", "--cached", "--name-only").stdout == ""

    def test_a_park_keeps_what_is_pending_and_drops_what_main_holds(self, mail, machines, tmp_path):
        """Dies to: a records ref that grows forever, or one that drops a row no
        lane has folded yet."""
        mac, origin = machines["mac"], machines["origin"]
        first, second, third = (f"2026-10-16-0{h}0101-mac.md" for h in (1, 2, 3))
        _park(mail, mac, first)
        _park(mail, mac, second)
        _main_rows(machines, tmp_path, first)
        _git(mac, "fetch", "--quiet", "origin")
        _park(mail, mac, third)
        assert _ref_rows(origin, "mac") == [f"{_ROW_DIR}/{second}", f"{_ROW_DIR}/{third}"]

    def test_pending_is_what_no_branch_has_ever_added(self, mail, machines, tmp_path):
        """Dies to: pending read as on a ref but not in the tree, which brings a
        row the prune archived back on every fold."""
        mac, win = machines["mac"], machines["win"]
        folded, waiting = "2026-10-16-010101-mac.md", "2026-10-16-020101-mac.md"
        _park(mail, mac, folded)
        _park(mail, mac, waiting)
        _main_rows(machines, tmp_path, folded)
        _main_rows(machines, tmp_path, prune=(folded,))
        ok, problem = mail.fetch_records(win, run=_real_run(mail))
        assert ok, problem
        _git(win, "fetch", "--quiet", "origin")
        got = mail.pending(win, _ROW_DIR, ["origin/main", "HEAD"], run=_real_run(mail))
        assert [(m, p) for m, p, _ref in got] == [("mac", f"{_ROW_DIR}/{waiting}")]

    def test_an_unnamed_clone_parks_nothing(self, mail, machines, tmp_path):
        nameless = tmp_path / "nameless"
        _git(tmp_path, "clone", "--quiet", str(machines["origin"]), str(nameless))
        _identity(nameless, "nameless")
        with pytest.raises(mail.Unresolvable):
            _park(mail, nameless, "2026-10-16-010101-x.md")
        assert _git(machines["origin"], "for-each-ref", "refs/heads/records/").stdout == ""

    @staticmethod
    def _lane(win: Path) -> None:
        _git(win, "pull", "--quiet", "--ff-only", "origin", "main")
        _git(win, "switch", "--quiet", "-c", "lane/win-work")
        (win / "work.txt").write_text("work\n", encoding="utf-8")
        _git(win, "add", "work.txt")
        _git(win, "commit", "--quiet", "-m", "feat: work")

    def test_a_lane_push_folds_the_pending_rows_in_then_prunes_to_the_cap(
        self, mail, ship_driver, fragments, machines, tmp_path
    ):
        """The assign's red: two seats, a pending ref. Dies to: no fold (the row
        waits for a pull request of its own), one commit that adds and prunes (a
        row older than the window then never enters history and re-folds on
        every push), a fold without its trailer (the lane's own-row checks read
        another seat's row as this lane's), or a second fold of the same row."""
        mac, win = machines["mac"], machines["win"]
        older = [f"2026-10-1{d}-120000-air.md" for d in (1, 2, 3)]
        _main_rows(machines, tmp_path, *older)
        parked = "2026-10-16-010101-mac.md"
        _park(mail, mac, parked)
        self._lane(win)
        assert ship_driver._fold_session_log(win, "main", keep=3, slack=0) == (1, 1)
        subjects = _git(win, "log", "--reverse", "--format=%s", "origin/main..HEAD").stdout.split("\n")
        assert len([s for s in subjects if s]) == 3, subjects
        fold_sha, prune_sha = _git(win, "log", "--format=%H", "-2", "HEAD").stdout.split()[::-1]
        for sha in (fold_sha, prune_sha):
            assert fragments.FOLD_TRAILER in _git(win, "log", "-1", "--format=%B", sha).stdout
        assert _git(win, "diff-tree", "--no-commit-id", "--name-status", "-r", fold_sha).stdout.split() == [
            "A", f"{_ROW_DIR}/{parked}"]
        assert _git(win, "diff-tree", "--no-commit-id", "--name-status", "-r", prune_sha).stdout.split() == [
            "D", f"{_ROW_DIR}/{older[0]}"]
        assert sorted(p.name for p in (win / _ROW_DIR).iterdir()) == sorted([*older[1:], parked])
        # The committed blob, not the checkout: under core.autocrlf=true (the
        # Windows default) the working tree reads CRLF and measures the host,
        # not the fold (win's drive, git 2.52.0.windows.1, DEF-5011).
        committed = subprocess.run(["git", "show", f"HEAD:{_ROW_DIR}/{parked}"], cwd=win, capture_output=True,
                                   check=True, timeout=45, env=_git_env()).stdout
        assert committed == _row(parked)
        assert ship_driver._fold_session_log(win, "main", keep=3, slack=0) == (0, 0)
        # Air 847e2b: the fold's row is no row of this lane, and the lane's own still is.
        assert ship_driver.lane_carries_memory_row("main", win) is False
        own = win / _ROW_DIR / "2026-10-16-030101-win.md"
        own.write_bytes(_row(own.name))
        _git(win, "add", "--", str(own.relative_to(win)))
        _git(win, "commit", "--quiet", "-m", "docs: handoff row")
        assert ship_driver.lane_carries_memory_row("main", win) is True

    def test_a_row_older_than_the_window_is_folded_once_and_never_again(
        self, mail, ship_driver, machines, tmp_path
    ):
        """Dies to: pending read against main alone, so a row the lane added and
        pruned in one push comes back on the next push of the same lane; and,
        after the lane lands as GitHub lands it (a --no-ff merge, the directory
        net unchanged), history simplification dropping that side of the merge,
        so the row read pending again at every later fold and its parker's ref
        kept it forever (both reviews of DEF-5007, driven)."""
        mac, win, origin = machines["mac"], machines["win"], machines["origin"]
        _main_rows(machines, tmp_path, *[f"2026-10-1{d}-120000-air.md" for d in (1, 2, 3)])
        old = "2026-01-02-120000-mac.md"
        _park(mail, mac, old)
        self._lane(win)
        assert ship_driver._fold_session_log(win, "main", keep=3, slack=0) == (1, 1)
        assert not (win / _ROW_DIR / old).exists()
        assert ship_driver._fold_session_log(win, "main", keep=3, slack=0) == (0, 0)
        _git(win, "push", "--quiet", "origin", "lane/win-work")
        keeper = tmp_path / "keeper"
        _git(keeper, "fetch", "--quiet", "origin")
        _git(keeper, "merge", "--quiet", "--no-ff", "-m", "Merge pull request #1", "origin/lane/win-work")
        _git(keeper, "push", "--quiet", "origin", "main")
        _git(win, "fetch", "--quiet", "origin")
        _git(win, "switch", "--quiet", "-c", "lane/win-next", "origin/main")
        assert ship_driver._fold_session_log(win, "main", keep=3, slack=0) == (0, 0)
        _git(mac, "fetch", "--quiet", "origin")
        _park(mail, mac, "2026-10-16-020101-mac.md")
        assert f"{_ROW_DIR}/{old}" not in _ref_rows(origin, "mac")

    def test_the_fold_prunes_only_past_the_slack_and_then_back_to_the_cap(
        self, mail, ship_driver, machines, tmp_path
    ):
        """Air fc87ad: dies to an exact cap, a prune commit on every lane that
        brings a row to a full main (eight such commits on main in three days)."""
        mac, win = machines["mac"], machines["win"]
        _main_rows(machines, tmp_path, *[f"2026-10-1{d}-120000-air.md" for d in (1, 2, 3, 4)])
        _park(mail, mac, "2026-10-16-010101-mac.md")
        self._lane(win)
        assert ship_driver._fold_session_log(win, "main", keep=3, slack=2) == (1, 0)   # 5: inside the slack
        _park(mail, mac, "2026-10-16-020101-mac.md")
        assert ship_driver._fold_session_log(win, "main", keep=3, slack=2) == (1, 3)   # 6: back to the cap
        assert len(list((win / _ROW_DIR).iterdir())) == 3

    def test_two_lanes_off_one_base_stay_inside_the_slack_with_no_prune_commit(
        self, ship_driver, machines, tmp_path
    ):
        """The failure-mode review's two-lane overshoot (DEF-5007 did not end it
        at an exact cap): each lane adds its own row off one base, each folds,
        both land; main holds the two rows inside the slack and no lane paid a
        prune commit."""
        _main_rows(machines, tmp_path, *[f"2026-10-1{d}-120000-air.md" for d in (1, 2, 3)])
        keeper = tmp_path / "keeper"
        for seat in ("mac", "win"):
            clone = machines[seat]
            _git(clone, "pull", "--quiet", "--ff-only", "origin", "main")
            _git(clone, "switch", "--quiet", "-c", f"lane/{seat}")
            row = clone / _ROW_DIR / f"2026-10-16-0{1 if seat == 'mac' else 2}0101-{seat}.md"
            row.write_bytes(_row(row.name))
            _git(clone, "add", "--", str(row.relative_to(clone)))
            _git(clone, "commit", "--quiet", "-m", f"docs: {seat}'s row")
            assert ship_driver._fold_session_log(clone, "main", keep=3, slack=2) == (0, 0)
            _git(clone, "push", "--quiet", "origin", f"lane/{seat}")
        _git(keeper, "fetch", "--quiet", "origin")
        for seat in ("mac", "win"):
            _git(keeper, "merge", "--quiet", "--no-ff", "-m", f"Merge {seat}", f"origin/lane/{seat}")
        assert len(list((keeper / _ROW_DIR).iterdir())) == 5
        assert "prune" not in _git(keeper, "log", "--format=%s", "-8").stdout

    def test_a_park_moves_the_branch_back_so_the_checkout_catches_up(self, mail, ship_driver, machines):
        """Both reviews' BLOCKER: the row's commit left ahead held SessionStart's
        catch-up on the parked lane (ahead 1) and passed the --early question as
        a row of the next lane's. Dies to: the branch left where the park found
        it, or a park of the working tree's bytes rather than the committed blob."""
        mac, origin = machines["mac"], machines["origin"]
        _git(mac, "fetch", "--quiet", "origin")
        before = _git(mac, "rev-parse", "origin/main").stdout.strip()
        row = mac / _ROW_DIR / "2026-10-16-010101-mac.md"
        row.parent.mkdir(parents=True, exist_ok=True)
        row.write_bytes(_row(row.name))
        _git(mac, "add", "--", str(row.relative_to(mac)))
        _git(mac, "commit", "--quiet", "-m", "docs: the handoff's row")
        assert ship_driver._park_the_row(mac, "main") is True
        assert _git(mac, "rev-parse", "HEAD").stdout.strip() == before
        assert _git(mac, "rev-list", "--count", "origin/main..HEAD").stdout.strip() == "0"
        raw = subprocess.run(["git", "cat-file", "-p", f"refs/heads/records/mac:{_ROW_DIR}/{row.name}"], cwd=origin,
                             capture_output=True, env=_git_env(), check=True, timeout=45).stdout
        assert raw == _row(row.name)

    def test_a_lane_whose_own_commit_quotes_the_trailer_still_carries_its_row(self, ship_driver, machines):
        """Dies to: the fold trailer matched anywhere in a body, so a commit that
        explains the fold in prose hid the lane's own row and asked for --early."""
        win = machines["win"]
        self._lane(win)
        row = win / _ROW_DIR / "2026-10-16-030101-win.md"
        row.parent.mkdir(parents=True, exist_ok=True)
        row.write_bytes(_row(row.name))
        _git(win, "add", "--", str(row.relative_to(win)))
        _git(win, "commit", "--quiet", "-m", "docs: the row",
             "-m", "The fold marks its commits with\nEspalier-Fold: session-log\nand this one is no fold.",
             "-m", "Co-Authored-By: Someone <someone@example.invalid>")
        assert ship_driver.lane_carries_memory_row("main", win) is True

    def test_a_fold_whose_commit_fails_leaves_the_tree_as_it_was(self, mail, ship_driver, machines, tmp_path):
        """Dies to: another seat's rows left staged after a failed commit, which a
        later hand commit would carry without the trailer as this lane's own."""
        mac, win = machines["mac"], machines["win"]
        _park(mail, mac, "2026-10-16-010101-mac.md")
        self._lane(win)
        from tests._stubs import write_stub
        write_stub(win / ".git" / "hooks" / "commit-msg", "#!/bin/sh\nexit 1\n")
        assert ship_driver._fold_session_log(win, "main", keep=3, slack=0) == (0, 0)
        assert _git(win, "status", "--porcelain").stdout == ""
        assert not (win / _ROW_DIR / "2026-10-16-010101-mac.md").exists()


def _relining_run(mail):
    """The real runner, with what the Windows pipe does to text input: a spawn
    there writes ``input=`` in text mode, which re-lines every ``\\n`` as ``\\r\\n``
    before git reads it (``_json_safe.run_bounded``'s Popen path)."""
    real = _real_run(mail)

    def run(argv, **kw):
        if kw.get("input") is not None:
            kw["input"] = kw["input"].replace("\n", "\r\n")
        return real(argv, **kw)
    return run


def _dropping_run(mail):
    """The real runner with every index update a no-op: the empty tree Windows
    git wrote when it would not take a path ending in a carriage return."""
    real = _real_run(mail)

    def run(argv, **kw):
        if argv[:2] == ["git", "update-index"]:
            return 0, "", ""
        return real(argv, **kw)
    return run


class TestTheTreeIsReadBackBeforeAnyPush:
    """A Windows seat's send pushed an empty mail tree (win, 2026-10-16 10:08Z):
    the builder fed ``update-index --index-info`` its lines on stdin, the Windows
    text pipe re-lined them, and git indexed ``mail.jsonl\\r`` or nothing. Every
    message that seat had sent vanished from origin's tip. The builder takes
    its entries as arguments again, and the tree it wrote is read back before
    any ref moves: one that does not hold exactly the entries it was given
    refuses, on a send and on a park alike, so no future builder pushes an empty
    tree. No POSIX cell sees the pipe; these runners stand in for it."""

    def test_entries_reach_the_tree_through_a_relining_pipe(self, mail, machines):
        mac = machines["mac"]
        blob = mail._hash_blob(mac, b'{"x": 1}\n', run=_real_run(mail))
        commit = mail._commit_entries(mac, {"mail.jsonl": blob, "a/b.md": blob}, None, "s",
                                      run=_relining_run(mail))
        names = _git(mac, "ls-tree", "-r", "-z", "--name-only", commit).stdout.split("\0")
        assert sorted(n for n in names if n) == ["a/b.md", "mail.jsonl"]

    def test_a_tree_without_its_entries_refuses_and_moves_nothing(self, mail, machines):
        mac = machines["mac"]
        blob = mail._hash_blob(mac, b"x\n", run=_real_run(mail))
        with pytest.raises(mail.Unresolvable, match="mail.jsonl"):
            mail._commit_entries(mac, {"mail.jsonl": blob}, None, "s", run=_dropping_run(mail))

    def test_a_send_that_would_push_an_empty_tree_refuses_and_origin_keeps_its_mail(self, mail, machines):
        mac, origin = machines["mac"], machines["origin"]
        first = mail.send(mac, _msg(mail, "mac", "note", "kept"), run=_real_run(mail), say=lambda _s: None)
        with pytest.raises(mail.Unresolvable):
            mail.send(mac, _msg(mail, "mac", "note", "lost"), run=_dropping_run(mail), say=lambda _s: None)
        assert _git(origin, "rev-parse", "refs/heads/mail/mac").stdout.strip() == first
        assert _git(mac, "rev-parse", "refs/heads/mail/mac").stdout.strip() == first
        assert "kept" in _origin_file(origin, "mac")

    def test_a_park_that_would_push_an_empty_tree_refuses(self, mail, machines):
        mac, origin = machines["mac"], machines["origin"]
        name = "2026-10-16-101010-mac.md"
        with pytest.raises(mail.Unresolvable):
            mail.park(mac, f"{_ROW_DIR}/{name}", _row(name), "origin/main", run=_dropping_run(mail),
                      say=lambda _s: None)
        for repo in (origin, mac):
            assert _git(repo, "rev-parse", "--verify", "--quiet", "refs/heads/records/mac",
                        check=False).returncode != 0

    @staticmethod
    def _rewriting_run(mail, rewrite):
        """The real runner with ``rewrite`` applied to ``update-index``'s
        arguments: a builder that loses or renames an entry on its way to git."""
        real = _real_run(mail)

        def run(argv, **kw):
            if argv[:2] == ["git", "update-index"]:
                argv = rewrite(list(argv))
            return real(argv, **kw)
        return run

    def test_a_tree_short_of_one_entry_refuses_naming_it(self, mail, machines):
        mac = machines["mac"]
        blob = mail._hash_blob(mac, b"x\n", run=_real_run(mail))
        short = self._rewriting_run(mail, lambda argv: argv[:-2])   # the last --cacheinfo pair dropped
        with pytest.raises(mail.Unresolvable, match="missing: `mail.jsonl`") as refused:
            mail._commit_entries(mac, {"a.md": blob, "mail.jsonl": blob}, None, "s", run=short)
        assert "do not retry" in str(refused.value)

    def test_a_renamed_entry_refuses(self, mail, machines):
        """The defect's own shape, a name that gains a carriage return. Apple git
        indexes it and the read-back refuses; Windows git refuses the path
        itself at update-index (win's drive, git 2.52.0.windows.1, DEF-5011).
        Either refusal is right: what matters is that nothing is pushed."""
        mac, origin = machines["mac"], machines["origin"]
        renamed = self._rewriting_run(mail, lambda argv: [a + "\r" if a.startswith("100644,") else a for a in argv])
        with pytest.raises(mail.Unresolvable, match=r"missing: `mail\.jsonl`|Invalid path"):
            mail.send(mac, _msg(mail, "mac", "note", "x"), run=renamed, say=lambda _s: None)
        for repo in (origin, mac):
            assert _git(repo, "rev-parse", "--verify", "--quiet", "refs/heads/mail/mac", check=False).returncode != 0

    def test_no_entries_refuse(self, mail, machines):
        with pytest.raises(mail.Unresolvable, match="no files"):
            mail._commit_entries(machines["mac"], {}, None, "s", run=_real_run(mail))

    def test_the_push_refuses_any_builders_empty_tree(self, mail, machines):
        mac, origin = machines["mac"], machines["origin"]
        empty = _git(mac, "commit-tree", "4b825dc642cb6eb9a060e54bf8d69288fbee4904", "-m", "e").stdout.strip()
        with pytest.raises(mail.Unresolvable, match="tree is empty"):
            mail._push_ref(mac, "mac", "refs/heads/mail/mac", "refs/remotes/origin/mail/mac", lambda _parent: empty,
                           run=_real_run(mail), timeout=30, verb=("send", "sent"))
        for repo in (origin, mac):
            assert _git(repo, "rev-parse", "--verify", "--quiet", "refs/heads/mail/mac", check=False).returncode != 0

    def test_a_parked_row_whose_name_git_quotes_is_carried_forward(self, mail, machines):
        mac, origin = machines["mac"], machines["origin"]
        first, second = "2026-10-16-101010-café.md", "2026-10-16-101011-mac.md"
        for name in (first, second):
            mail.park(mac, f"{_ROW_DIR}/{name}", f"| {name} |\n".encode("utf-8"), "origin/main",
                      run=_real_run(mail), say=lambda _s: None)
        names = _git(origin, "ls-tree", "-r", "-z", "--name-only", "refs/heads/records/mac").stdout.split("\0")
        assert sorted(n for n in names if n) == [f"{_ROW_DIR}/{first}", f"{_ROW_DIR}/{second}"]

    def test_the_runner_refuses_lines_of_text_on_stdin(self, mail, machines):
        with pytest.raises(mail.Unresolvable, match="re-lines"):
            mail.run(["git", "hash-object", "--stdin"], cwd=str(machines["mac"]), input="a\nb\n")
