# pytest-marker: default-unit  (a frozen-fixture census and planted scratch refs; TP-701 Wave C)
# slow-exempt: one planted repository of mail refs drives git; the file runs in about a second (2026-10-15)
"""Pins ``scripts/mail_latency_census.py``: a worker request's wait for its
first answer, the dispatcher split's pre-registered metric (TP-701 Wave C).

The live mail refs move every minute, so the figures are pinned on a fixture
frozen from them at Wave C's start (2026-10-15 02:20Z): the fields the pairing
reads, no prose. Two readings are pinned there: the dispatcher's own hand count,
reproduced exactly (its run at 02:10:45Z, a floor-rank p75, one ask still open:
n=21, 268, 722, 8264 and 18 answered, 6, 8, 16), and the instrument's figures at
02:20Z with its nearest-rank p75 (n=21, 268, 726, 8264 and n=19, 6, 10, 16),
which supersede the hand count's (air, 2026-10-15). Each rule the pairing
states has a planted case that reds when the rule is broken, the named mutation
among them: pairing an ack by its own time order instead of its ``ack`` field.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests._git_oracle import _git_env

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "mail_latency_census.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "mail_latency" / "refs-2026-10-15T0220Z.json"

if not MODULE_PATH.is_file():  # pragma: no cover - adopter tree
    pytest.skip("scripts/mail_latency_census.py is self-host dev tooling", allow_module_level=True)


def _load():
    spec = importlib.util.spec_from_file_location("mail_latency_census", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mlc():
    return _load()


def _m(id_: str, type_: str, sender: str, at: str, ack: str = "") -> dict:
    out = {"id": id_, "type": type_, "from": sender, "at": at}
    if ack:
        out["ack"] = ack
    return out


def _stamp(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


NOW = _stamp("2026-10-15T12:00:00Z")


class TestTheFrozenFigures:
    def test_the_fixture_reads_the_instruments_figures(self, mlc):
        messages, dispatcher, frozen = mlc.read_fixture(FIXTURE)
        assert dispatcher == "air" and frozen == _stamp("2026-10-15T02:20:00Z")
        data = mlc.report(messages, dispatcher, [(None, mlc.SPLIT), (mlc.SPLIT, frozen)], frozen, frozen)
        before, since = data["windows"]
        assert (before["answered"], before["median"], before["p75"], before["max"]) == (21, 268, 726, 8264)
        assert (since["answered"], since["median"], since["p75"], since["max"]) == (19, 6, 10, 16)
        assert before["unanswered"] == [] and since["unanswered"] == [] and data["skipped"] == 0

    def test_the_dispatchers_hand_count_is_reproduced_exactly(self, mlc):
        """C-0 item 2's oracle: the 2026-10-14 report was a run at
        2026-10-15T02:10:45Z with a floor-rank p75 (``int(0.75 * n) - 1``) and
        one ask still open since; read that way, the instrument gives its
        figures to the minute. The two gaps from the instrument's own figures
        are the run's time and the rank rule, not a pair."""
        messages, dispatcher, _frozen = mlc.read_fixture(FIXTURE)
        at = _stamp("2026-10-15T02:10:45Z")
        seen = [m for m in messages if _stamp(m["at"]) <= at]
        rows, _skipped = mlc.pair(seen, dispatcher, at)
        for (since, until), expected in (((None, mlc.SPLIT), (21, 0, 268, 722, 8264)),
                                         ((mlc.SPLIT, at), (18, 1, 6, 8, 16))):
            inside = [r for r in rows if (since is None or _stamp(r["at"]) >= since) and _stamp(r["at"]) < until]
            xs = sorted(r["minutes"] for r in inside if r["minutes"] is not None)
            floor_p75 = xs[int(0.75 * len(xs)) - 1]
            got = (len(xs), sum(r["minutes"] is None for r in inside), round(sorted(xs)[len(xs) // 2]),
                   round(floor_p75), round(max(xs)))
            assert got == expected

    def test_the_fixture_carries_no_prose(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        fields = {k for ms in data["messages"].values() for m in ms for k in m}
        assert fields <= {"id", "type", "from", "at", "ack"}, fields


class TestThePairing:
    def test_an_ack_answers_the_request_its_ack_field_names_not_the_nearest_one(self, mlc):
        """The named mutation: pair by time order and A takes B's earlier ack."""
        rows, _ = mlc.pair([
            _m("A", "request", "win", "2026-10-14T10:00:00Z"),
            _m("B", "request", "win-2", "2026-10-14T10:01:00Z"),
            _m("x", "ack", "air", "2026-10-14T10:02:00Z", ack="B"),
            _m("y", "ack", "air", "2026-10-14T10:30:00Z", ack="A"),
        ], "air")
        assert {r["id"]: r["minutes"] for r in rows} == {"A": 30.0, "B": 1.0}

    def test_the_first_answer_counts_and_a_note_naming_the_id_answers_nothing(self, mlc):
        rows, _ = mlc.pair([
            _m("A", "request", "win", "2026-10-14T10:00:00Z"),
            _m("n", "note", "air", "2026-10-14T10:01:00Z", ack="A"),
            _m("y", "ack", "air", "2026-10-14T10:20:00Z", ack="A"),
            _m("z", "ack", "win-2", "2026-10-14T10:05:00Z", ack="A"),
        ], "air")
        assert rows[0]["minutes"] == 5.0 and rows[0]["answered_by"] == "win-2"

    def test_an_ack_stamped_before_its_request_is_not_its_answer(self, mlc):
        rows, _ = mlc.pair([
            _m("A", "request", "win", "2026-10-14T10:00:00Z"),
            _m("x", "ack", "air", "2026-10-14T09:00:00Z", ack="A"),
            _m("y", "ack", "air", "2026-10-14T10:07:00Z", ack="A"),
        ], "air")
        assert rows[0]["minutes"] == 7.0

    def test_the_askers_own_ack_is_no_ones_answer(self, mlc):
        """A request its asker closed (moot, withdrawn) leaves the figures and
        is listed; an answer from another seat after it still counts."""
        data = mlc.report([
            _m("A", "request", "win", "2026-10-14T10:00:00Z"),
            _m("x", "ack", "win", "2026-10-14T10:01:00Z", ack="A"),
            _m("B", "request", "win", "2026-10-14T11:00:00Z"),
            _m("y", "ack", "win", "2026-10-14T11:01:00Z", ack="B"),
            _m("z", "ack", "air", "2026-10-14T11:09:00Z", ack="B"),
        ], "air", [(None, None)], NOW)
        (w,) = data["windows"]
        assert (w["answered"], w["median"], w["closed_by_asker"], w["unanswered"]) == (1, 9, ["A"], [])

    def test_the_dispatchers_own_request_is_not_a_worker_request(self, mlc):
        rows, _ = mlc.pair([
            _m("D", "request", "air", "2026-10-14T10:00:00Z"),
            _m("W", "request", "win", "2026-10-14T10:00:00Z"),
        ], "air")
        assert [r["id"] for r in rows] == ["W"]

    def test_a_stamp_that_does_not_parse_is_skipped_and_counted_not_a_crash(self, mlc):
        rows, skipped = mlc.pair([
            _m("A", "request", "win", "2026-10-14T10:00:00.5Z"),
            _m("B", "request", "win", "2026-10-14T10:00:00Z"),
            _m("x", "ack", "air", "garbage", ack="B"),
            _m("y", "ack", "air", "2026-10-14T10:03:00Z", ack="B"),
        ], "air")
        assert skipped == 2 and [(r["id"], r["minutes"]) for r in rows] == [("B", 3.0)]


class TestTheWindow:
    def test_an_unanswered_request_is_listed_with_its_age_and_out_of_the_figures(self, mlc):
        data = mlc.report([
            _m("A", "request", "win", "2026-10-15T10:00:00Z"),
            _m("B", "request", "win", "2026-10-15T09:00:00Z"),
            _m("y", "ack", "air", "2026-10-15T09:04:00Z", ack="B"),
        ], "air", [(None, None)], NOW)
        (w,) = data["windows"]
        assert (w["answered"], w["median"], w["max"]) == (1, 4, 4)
        assert w["unanswered"] == [{"id": "A", "from": "win", "at": "2026-10-15T10:00:00Z", "age_minutes": 120.0}]

    def test_within_the_hour_counts_an_old_unanswered_ask_as_a_miss(self, mlc):
        """The pre-registered metric: an ask still open past the hour is a
        miss, so a slow dispatcher's silence cannot flatter the figure."""
        data = mlc.report([
            _m("A", "request", "win", "2026-10-15T09:00:00Z"),
            _m("x", "ack", "air", "2026-10-15T09:10:00Z", ack="A"),
            _m("B", "request", "win", "2026-10-15T08:00:00Z"),
            _m("y", "ack", "air", "2026-10-15T09:30:00Z", ack="B"),
            _m("C", "request", "win", "2026-10-15T09:00:00Z"),
        ], "air", [(None, None)], NOW)
        (w,) = data["windows"]
        assert (w["within_hour"], w["past_the_hour"]) == (1, 2)

    def test_until_bounds_the_answers_too(self, mlc):
        """Read as of ``--until``, an ask answered after it was still waiting."""
        until = _stamp("2026-10-14T11:00:00Z")
        data = mlc.report([
            _m("A", "request", "win", "2026-10-14T10:00:00Z"),
            _m("y", "ack", "air", "2026-10-14T12:00:00Z", ack="A"),
        ], "air", [(None, until)], until, until)
        (w,) = data["windows"]
        assert w["answered"] == 0 and w["unanswered"][0]["age_minutes"] == 60.0

    def test_a_request_belongs_to_the_window_its_own_stamp_falls_in(self, mlc):
        split = _stamp("2026-10-14T12:00:00Z")
        data = mlc.report([
            _m("A", "request", "win", "2026-10-14T11:50:00Z"),
            _m("y", "ack", "air", "2026-10-14T12:30:00Z", ack="A"),
        ], "air", [(None, split), (split, None)], NOW)
        assert [w["answered"] for w in data["windows"]] == [1, 0]


class TestTheEstimator:
    @pytest.mark.parametrize("values, expected", [
        ([4.0], 4.0), ([1.0, 2.0, 3.0, 4.0], 3.0), ([5.0, 1.0, 4.0, 2.0, 3.0], 4.0), ([], None),
    ])
    def test_p75_is_nearest_rank_a_value_that_occurred(self, mlc, values, expected):
        assert mlc.p75(values) == expected


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    # the repository-selecting overrides stripped (a hook's GIT_DIR would point
    # these writes at the live clone's refs), and bytes in: a text-mode stdin
    # writes CRLF on Windows, and mktree then names the entry `mail.jsonl\r`
    env = {**_git_env(), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", str(repo), *args],
                          input=stdin.encode("utf-8") if stdin is not None else None, check=True,
                          capture_output=True, env=env).stdout.decode("utf-8").strip()


def _ref_with(repo: Path, ref: str, body: str, name: str = "mail.jsonl") -> None:
    blob = _git(repo, "hash-object", "-w", "--stdin", stdin=body)
    tree = _git(repo, "mktree", stdin=f"100644 blob {blob}\t{name}\n")
    _git(repo, "update-ref", ref, _git(repo, "commit-tree", tree, "-m", "mail"))


def _lines(*messages: dict) -> str:
    # a channel line carries a `re` object (tools/cc/mail.py::decode_lines skips one without)
    return "".join(json.dumps({**m, "re": {}}) + "\n" for m in messages)


@pytest.fixture
def mail_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    return repo


class TestTheRefs:
    def test_every_mail_ref_is_read_and_a_message_on_two_is_counted_once(self, mlc, mail_repo):
        """The remote-tracking copies and this clone's own ref (which may be
        ahead of origin's) are both read; the same id read twice is one."""
        req = _m("20261014T100000Z-win-aaaaaa", "request", "win", "2026-10-14T10:00:00Z")
        ahead = _m("20261014T110000Z-win-cccccc", "request", "win", "2026-10-14T11:00:00Z")
        ack = _m("20261014T100500Z-air-bbbbbb", "ack", "air", "2026-10-14T10:05:00Z", ack=req["id"])
        _ref_with(mail_repo, "refs/remotes/origin/mail/win", _lines(req))
        _ref_with(mail_repo, "refs/heads/mail/win", _lines(req, ahead))  # one message ahead of origin's
        _ref_with(mail_repo, "refs/remotes/origin/mail/air", _lines(ack))
        messages, tips = mlc.read_refs(mail_repo)
        assert sorted(m["id"] for m in messages) == sorted([req["id"], ahead["id"], ack["id"]])
        assert [r["minutes"] for r in mlc.pair(messages, "air")[0]] == [5.0, None]
        assert tips["refs/heads/mail/win"] == "2026-10-14T11:00:00Z"

    def test_a_ref_without_mail_and_an_undecodable_line_cost_only_themselves(self, mlc, mail_repo):
        req = _m("20261014T100000Z-win-aaaaaa", "request", "win", "2026-10-14T10:00:00Z")
        _ref_with(mail_repo, "refs/remotes/origin/mail/win", _lines(req) + "not json\n")
        _ref_with(mail_repo, "refs/remotes/origin/mail/odd", "x\n", name="other.txt")
        messages, tips = mlc.read_refs(mail_repo)
        assert [m["id"] for m in messages] == [req["id"]] and "refs/remotes/origin/mail/odd" not in tips

    def test_no_mail_refs_is_a_note_not_an_error(self, mlc, mail_repo, capsys):
        assert mlc.main(["--repo", str(mail_repo), "--no-fetch"]) == 0
        assert "no mail refs" in capsys.readouterr().out

    def test_an_unusable_dispatcher_setting_refuses_a_plain_window(self, mlc, mail_repo, capsys):
        """An unreadable setting would count the dispatcher's own asks as a
        worker's; the census refuses rather than skew the median. ``--split``
        names its own dispatcher and is not refused."""
        req = _m("20261014T100000Z-win-aaaaaa", "request", "win", "2026-10-14T10:00:00Z")
        _ref_with(mail_repo, "refs/remotes/origin/mail/win", _lines(req))
        (mail_repo / "espalier.toml").write_bytes(b'dispatcher = "Not A Name"\n')
        assert mlc.main(["--repo", str(mail_repo), "--no-fetch"]) == 1
        assert "unusable" in capsys.readouterr().err
        assert mlc.main(["--repo", str(mail_repo), "--no-fetch", "--split"]) == 0


    def test_split_reads_the_splits_own_dispatcher_whatever_the_setting_names(self, mlc, mail_repo, capsys):
        """The pre-registered baseline does not move when the dispatcher role
        does: ``--split`` counts air's asks out even when espalier.toml names
        another seat."""
        _ref_with(mail_repo, "refs/remotes/origin/mail/air",
                  _lines(_m("20261014T100000Z-air-aaaaaa", "request", "air", "2026-10-14T10:00:00Z")))
        _ref_with(mail_repo, "refs/remotes/origin/mail/win",
                  _lines(_m("20261014T110000Z-win-bbbbbb", "request", "win", "2026-10-14T11:00:00Z")))
        (mail_repo / "espalier.toml").write_bytes(b'dispatcher = "win-2"\n')
        assert mlc.main(["--repo", str(mail_repo), "--no-fetch", "--split", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["dispatcher"] == "air" and data["requests"] == 1


class TestTheCli:
    def test_split_on_the_fixture_prints_both_windows(self, mlc, capsys):
        assert mlc.main(["--fixture", str(FIXTURE), "--split"]) == 0
        out = capsys.readouterr().out
        assert "21 of 21 answered, median 268 min, p75 726 min (nearest-rank), max 8264 min" in out
        assert "19 of 19 answered, median 6 min, p75 10 min (nearest-rank), max 16 min" in out

    def test_json_carries_the_same_windows(self, mlc, capsys):
        assert mlc.main(["--fixture", str(FIXTURE), "--split", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert [w["answered"] for w in data["windows"]] == [21, 19]

    @pytest.mark.parametrize("argv", [
        ["--split", "--since", "2026-10-01"], ["--since", "yesterday"],
        ["--split", "--until", "2026-10-10"], ["--since", "2026-10-14", "--until", "2026-10-13"],
    ])
    def test_a_bad_window_is_a_usage_error(self, mlc, argv, capsys):
        assert mlc.main(["--fixture", str(FIXTURE), *argv]) == 2

    def test_an_unreadable_fixture_is_a_usage_error(self, mlc, tmp_path, capsys):
        assert mlc.main(["--fixture", str(tmp_path / "missing.json")]) == 2
