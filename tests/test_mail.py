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
        assert mail.clone_machine(tmp_path / "feat") == "win"
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
        hook = origin / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho 'no mail today' >&2\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
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
