"""Contract tests for ``tools/cc/board.py``: one live read of what a seat needs
before it states state (TP-479 Wave A-3, layers L4 and L5; root CLAUDE.md Core
Rule 15). Three seats each believed a different branch was merging because each
read a snapshot; the board reads GitHub and the mail channel now.

Every read goes through an injected runner and stubbed channel calls, so the
oracle is the payload GitHub documents (``mergeStateStatus``, a run's
``status``/``conclusion``, the compare API's commits), driven in each shape.
"""
# pytest-marker: default-unit  (in-process calls into a path-loaded script through
# its injectable runner and stubbed channel reads: no subprocess, no git, no network)
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_CC = REPO_ROOT / "tools" / "cc"


def _load(name: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, TOOLS_CC / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def board():
    return _load("board", "board_under_test")


def _gh(answers: dict[str, object]):
    """A runner answering ``gh`` by its first words (``pr list``, ``run list``,
    ``api compare``); anything else is an unexpected call."""
    calls: list[list[str]] = []

    def run(argv, **kw):
        calls.append(list(argv))
        key = " ".join(argv[1:3]) if argv[1] != "api" else ("api compare" if "/compare/" in argv[2] else argv[2])
        if key not in answers:
            raise AssertionError(f"unexpected call {argv}")
        answer = answers[key]
        if isinstance(answer, Exception):
            raise answer
        return 0, json.dumps(answer), ""

    run.calls = calls  # type: ignore[attr-defined]
    return run


def _stub_channel(monkeypatch, board, by_machine=None, dispatcher="air", fetch=(True, ""), read_error=None,
                  sessions=None):
    # This clone's checkouts and their live sessions: git and Claude Code's
    # registry, which TestSeats drives for real over a scratch registry.
    monkeypatch.setattr(board, "read_sessions", lambda root, **kw: sessions or {"checkouts": [], "unread": ""})
    monkeypatch.setattr(board.mail, "machine_setting", lambda root, run=None: ("win", "stubbed"))
    monkeypatch.setattr(board.mail, "fetch_mail", lambda root, run=None: fetch)

    def read_mail(root, run=None):
        if read_error:
            raise board.Unresolvable(read_error)
        return by_machine or {}, {}

    monkeypatch.setattr(board.mail, "read_mail", read_mail)
    monkeypatch.setattr(board.mail, "dispatcher_setting", lambda root: (dispatcher, "stubbed reason"))
    monkeypatch.setattr(board._merge_rules, "base_branch", lambda root, deadline=None: "main")
    monkeypatch.setattr(board._merge_rules, "read", lambda root, deadline=None, base=None: (
        "main", 0, json.dumps({"strict": False, "contexts": ["a", "b"]})))
    # The stale-base section's git reads; TestStaleBaseSection drives the real one.
    monkeypatch.setattr(board, "read_stale_section", lambda *a, **k: None)
    # The base fetch and the ledger count at the base: git and a child
    # interpreter, which tests/test_board_ledger_base.py drives for real.
    monkeypatch.setattr(board, "fetch_base", lambda *a, **k: (True, ""))
    monkeypatch.setattr(board, "read_ledger_at_base", lambda *a, **k: None)


def _run(status: str, conclusion: str, sha: str) -> dict:
    return {"status": status, "conclusion": conclusion, "headSha": sha, "url": f"u-{sha[:3]}"}


def _merge(pr: int, sha: str, parents: int = 2) -> dict:
    return {"sha": sha, "parents": [{}] * parents,
            "commit": {"message": f"Merge pull request #{pr} from Mike/lane/x\n\nbody"}}


RED_SHA, GREEN_SHA = "abc1234" + "0" * 33, "9" * 40
_GREEN_RUNS = [_run("completed", "success", "a" * 40)]
_RED_THEN_GREEN = [_run("in_progress", "", "f" * 40), _run("completed", "cancelled", "e" * 40),
                   _run("completed", "failure", RED_SHA), _run("completed", "success", GREEN_SHA)]


class TestLaneSeats:
    def test_a_shipped_lane_keeps_its_seat(self, board):
        """The ship driver releases a lane's claims once its push lands; the
        release still names whose lane it was."""
        mail = board.mail
        t = datetime(2026, 10, 9, 20, 0, 0, tzinfo=timezone.utc)
        claim = mail.new_message("win-2", "claim", "", lane="lane/x", now=t)
        release = mail.new_message("win-2", "release", "", lane="lane/x", now=t.replace(minute=5))
        assert mail.lane_seats({"win-2": [claim, release]}) == {"lane/x": "win-2"}
        later = mail.new_message("win", "claim", "", lane="lane/x", now=t.replace(minute=9))
        assert mail.lane_seats({"win-2": [claim, release], "win": [later]}) == {"lane/x": "win"}


class TestOpenPullRequests:
    def test_each_pr_reads_its_merge_state_and_seat(self, board, monkeypatch, tmp_path):
        """The state is GitHub's ``mergeStateStatus``, which says what holds a
        pull request; ``state`` only says OPEN. Dies to: the wrong field read."""
        claim = board.mail.new_message("win-2", "claim", "", lane="lane/b")
        _stub_channel(monkeypatch, board, {"win-2": [claim]})
        prs = [{"number": 7, "headRefName": "lane/a", "state": "OPEN", "mergeStateStatus": "DIRTY",
                "isDraft": False, "autoMergeRequest": {"x": 1}},
               {"number": 8, "headRefName": "lane/b", "state": "OPEN", "mergeStateStatus": "BEHIND",
                "isDraft": False, "autoMergeRequest": None}]
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": prs, "run list": _GREEN_RUNS})))
        assert "#7 lane/a [no seat's claim names this branch]: CONFLICTS with the base" in text
        assert "#8 lane/b [win-2]: behind the base (holds only under the up-to-date rule); auto-merge not armed" in text
        assert text.isascii()

    def test_unstable_reads_red_or_still_running(self, board, monkeypatch, tmp_path):
        """TP-701 A-3, measured 2026-10-15 on #211 (auto-merge off, every other
        check green): with only the optional artifact-parity re-run going (run
        38508632701), five reads from 05:36:13Z to 05:36:32Z said UNSTABLE, then
        CLEAN once it passed. A pending optional check is UNSTABLE, so "red"
        alone misread it (win-2's note 5f2ef0 on #207). The red half is not
        measured here. Dies to: the old wording."""
        _stub_channel(monkeypatch, board)
        prs = [{"number": 211, "headRefName": "lane/a", "mergeStateStatus": "UNSTABLE", "isDraft": False,
                "autoMergeRequest": None}]
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": prs, "run list": _GREEN_RUNS}), now=_NOW))
        assert "#211 lane/a [no seat's claim names this branch]: ready; an optional check is red or still " \
               "running; auto-merge not armed" in text, text

    def test_a_shipped_pull_request_still_shows_its_seat(self, board, monkeypatch, tmp_path):
        """The board's first live run named no seat for win-2's just-shipped
        pull request: the seat came from live claims. Dies to: seats from live
        claims."""
        mail = board.mail
        t = datetime(2026, 10, 9, 20, 0, 0, tzinfo=timezone.utc)
        claim = mail.new_message("win-2", "claim", "", lane="lane/shipped", now=t)
        release = mail.new_message("win-2", "release", "", lane="lane/shipped", now=t.replace(minute=5))
        _stub_channel(monkeypatch, board, {"win-2": [claim, release]})
        prs = [{"number": 9, "headRefName": "lane/shipped", "mergeStateStatus": "BLOCKED",
                "isDraft": False, "autoMergeRequest": {"x": 1}}]
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": prs, "run list": _GREEN_RUNS})))
        assert "#9 lane/shipped [win-2]: blocked" in text
        assert "claims:   none live" in text


class TestStaleBaseSection:
    """The board reads the stale base for each pull request whose armed
    auto-merge would land it on its own green CI (TP-479 B-3), and only with
    the up-to-date rule off; the read itself is pinned against real git in
    tests/test_stale_base.py."""

    def test_only_an_armed_ready_pull_request_is_read_and_only_with_the_rule_off(self, board, monkeypatch, tmp_path):
        read: list = []
        monkeypatch.setattr(board, "read_stale", lambda root, base, pr, run_=None: read.append(pr["number"])
                            or f"near #{pr['number']}")
        prs = [{"number": 7, "autoMergeRequest": {"x": 1}}, {"number": 8, "autoMergeRequest": None},
               {"number": 9, "autoMergeRequest": {"x": 1}, "isDraft": True}]
        board.read_stale_section(tmp_path, "main", prs, False, fetch=False, run_=_gh({}))
        assert read == [7] and prs[0]["stale"] == "near #7" and "stale" not in prs[1]
        read.clear()
        board.read_stale_section(tmp_path, "main", [{"number": 7, "autoMergeRequest": {"x": 1}}], True,
                                 fetch=False, run_=_gh({}))
        assert read == []

    def test_one_failed_read_costs_only_its_line(self, board, monkeypatch, tmp_path):
        def read_stale(root, base, pr, run_=None):
            if pr["number"] == 7:
                raise board.Unresolvable("gh run list took longer than 15s")
            return "near"
        monkeypatch.setattr(board, "read_stale", read_stale)
        prs = [{"number": 7, "autoMergeRequest": {"x": 1}}, {"number": 10, "autoMergeRequest": {"x": 1}}]
        board.read_stale_section(tmp_path, "main", prs, None, fetch=False, run_=_gh({}))
        assert prs[0]["stale"] == "stale-base check not read for #7: gh run list took longer than 15s"
        assert prs[1]["stale"] == "near"

    def test_read_stale_hands_the_files_runs_and_head_to_the_read(self, board, monkeypatch, tmp_path):
        seen: dict = {}

        def judged(root, **kw):
            seen.update(kw)
            return {"tested": "1" * 40, "now": "2" * 40, "moved": 1, "near": ["a.py (both changed)"], "unread": ""}

        monkeypatch.setattr(board._merge_rules, "stale_base", judged)
        head = "c" * 40
        runs = [{"workflowName": "CI", "createdAt": "2026-10-10T05:30:00Z", "headSha": head, "conclusion": "success"}]
        pr = {"number": 7, "headRefName": "lane/a", "headRefOid": head, "files": [{"path": "a.py"}, {"path": "b.md"}]}
        line = board.read_stale(tmp_path, "main", pr, run_=_gh({"run list": runs, "cat-file -e": ""}))
        assert seen["pr_paths"] == ["a.py", "b.md"] and seen["pr_rev"] == head
        assert seen["tested_when"] == "2026-10-10T05:30:00Z" and seen["base_ref"] == "origin/main"
        assert "main moved 1 merge(s) since #7's CI" in line

    def test_the_stale_line_sits_under_its_pull_request(self, board, monkeypatch, tmp_path):
        _stub_channel(monkeypatch, board)

        def section(root, base, prs, strict, *, fetch, run_=None):
            for pr in prs:
                if pr.get("autoMergeRequest"):
                    pr["stale"] = "main moved 1 merge(s) since #7's CI tested it on 1111111, near its files"

        monkeypatch.setattr(board, "read_stale_section", section)
        prs = [{"number": 7, "headRefName": "lane/a", "mergeStateStatus": "BLOCKED", "isDraft": False,
                "autoMergeRequest": {"x": 1}, "files": [{"path": "a.py"}]}]
        collected = board.collect(tmp_path, run_=_gh({"pr list": prs, "run list": _GREEN_RUNS}))
        assert "files" not in collected["open_prs"][0]   # read for the check, not carried in the JSON
        lines = board.render(collected).splitlines()
        at = next(i for i, ln in enumerate(lines) if "#7 lane/a" in ln)
        assert lines[at + 1] == "            stale: main moved 1 merge(s) since #7's CI tested it on 1111111, near its files"


class TestPostMergeVerdict:
    def test_one_merge_since_the_last_green_is_the_one_to_revert(self, board, monkeypatch, tmp_path):
        """A running or cancelled run is no verdict; the newest red one is, and
        the last green before it bounds the suspects. Dies to: the first run
        read whatever its status, or the red run's own head blamed."""
        _stub_channel(monkeypatch, board)
        merge_sha = "dddd111" + "1" * 33
        run = _gh({"pr list": [], "run list": _RED_THEN_GREEN,
                   "api compare": {"commits": [{"sha": "x", "parents": [{}],
                                                "commit": {"message": "fix(lane): a lane commit"}},
                                               _merge(42, merge_sha)]}})
        text = board.render(board.collect(tmp_path, run_=run))
        assert "main:     RED after #42 (post-merge proof on abc1234, u-abc)" in text
        assert "git switch -c revert/dddd111 origin/main && git revert -m 1 dddd111" in text
        assert any(f"/compare/{GREEN_SHA}...{RED_SHA}" in " ".join(c) for c in run.calls)

    def test_several_merges_name_suspects_and_no_revert(self, board, monkeypatch, tmp_path):
        """The workflow cancels an older run when a newer push lands, so a red
        run can carry several merges: naming the newest as the culprit would
        revert an innocent seat's work. Dies to: a revert printed for one of
        several suspects."""
        _stub_channel(monkeypatch, board)
        run = _gh({"pr list": [], "run list": _RED_THEN_GREEN,
                   "api compare": {"commits": [_merge(41, "1" * 40), _merge(42, "2" * 40)]}})
        text = board.render(board.collect(tmp_path, run_=run))
        assert "suspects #41, #42 (merged since the last green run on 9999999)" in text
        assert "git revert" not in text

    def test_no_green_in_the_window_makes_every_earlier_merge_a_suspect(self, board, monkeypatch, tmp_path):
        _stub_channel(monkeypatch, board)
        run = _gh({"pr list": [], "run list": [_run("completed", "failure", RED_SHA)]})
        text = board.render(board.collect(tmp_path, run_=run))
        assert "no green run in the last 20, so every merge before it is a suspect" in text
        assert "git revert" not in text

    def test_a_failed_suspects_read_keeps_the_red(self, board, monkeypatch, tmp_path):
        """The correctness review's major: a failed lookup turned a known red
        base into "unread". Dies to: the suspects read unguarded."""
        _stub_channel(monkeypatch, board)
        run = _gh({"pr list": [], "run list": _RED_THEN_GREEN,
                   "api compare": board.Unresolvable("gh api compare took longer than 15s")})
        text = board.render(board.collect(tmp_path, run_=run))
        assert "main:     RED (post-merge proof on abc1234" in text
        assert "the suspects could not be read (gh api compare took longer than 15s)" in text

    def test_a_skipped_or_neutral_run_is_no_verdict(self, board, monkeypatch, tmp_path):
        """Dies to: every non-SUCCESS conclusion read as red."""
        _stub_channel(monkeypatch, board)
        runs = [_run("completed", "skipped", "s" * 40), _run("completed", "neutral", "n" * 40)] + _GREEN_RUNS
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "run list": runs})))
        assert "main:     post-merge proof green on aaaaaaa" in text
        assert "RED" not in text

    def test_a_red_base_names_the_armed_pull_requests(self, board, monkeypatch, tmp_path):
        """Auto-merge lands an armed pull request on a red base: the board says
        which ones and how to disarm them."""
        _stub_channel(monkeypatch, board)
        prs = [{"number": 7, "headRefName": "lane/a", "mergeStateStatus": "CLEAN", "isDraft": False,
                "autoMergeRequest": {"x": 1}},
               {"number": 8, "headRefName": "lane/b", "mergeStateStatus": "CLEAN", "isDraft": False,
                "autoMergeRequest": None}]
        run = _gh({"pr list": prs, "run list": _RED_THEN_GREEN, "api compare": {"commits": [_merge(42, "2" * 40)]}})
        text = board.render(board.collect(tmp_path, run_=run))
        assert "auto-merge is armed on #7, which lands on the red base unless disarmed" in text

    def test_a_green_base_and_a_going_run(self, board, monkeypatch, tmp_path):
        _stub_channel(monkeypatch, board)
        runs = [_run("queued", "", "f" * 40)] + _GREEN_RUNS
        run = _gh({"pr list": [], "run list": runs})
        text = board.render(board.collect(tmp_path, run_=run))
        assert "main:     post-merge proof green on aaaaaaa; a newer run is going" in text
        assert not [c for c in run.calls if c[1] == "api"], "a green base asks for no suspects"

    def test_a_repository_without_the_post_merge_proof_says_so(self, board, monkeypatch, tmp_path):
        """`gh run list --workflow` on a workflow the repository does not have,
        recorded 2026-10-09: rc=1 and "HTTP 404: workflow <name> not found on
        the default branch (<url>)". A state to name, not a failed read."""
        _stub_channel(monkeypatch, board)
        missing = board.Unresolvable(
            "gh run list answered rc=1 with no JSON: HTTP 404: workflow post-merge.yml not found on the "
            "default branch (https://api.github.com/repos/o/r/actions/workflows/post-merge.yml)")
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "run list": missing})))
        assert "main:     no post-merge proof here (post-merge.yml is not in this repository)" in text


class TestMailSections:
    def test_one_unreadable_section_costs_only_itself(self, board, monkeypatch, tmp_path):
        _stub_channel(monkeypatch, board)
        run = _gh({"pr list": board.Unresolvable("gh is not on PATH"), "run list": _GREEN_RUNS})
        text = board.render(board.collect(tmp_path, run_=run))
        assert "open PRs: unread (gh is not on PATH)" in text
        assert "post-merge proof green" in text
        assert "merging:  main: up-to-date rule off" in text

    def test_an_unread_mail_never_reads_as_no_jobs_or_no_seat(self, board, monkeypatch, tmp_path):
        """The failure-mode review's major: a failed mail read printed "no live
        assignments" and a PR with no seat, which read as answers. Dies to: the
        jobs line or the seat label read from an empty fold."""
        _stub_channel(monkeypatch, board, read_error="git for-each-ref failed")
        prs = [{"number": 7, "headRefName": "lane/a", "mergeStateStatus": "CLEAN", "isDraft": False,
                "autoMergeRequest": None}]
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": prs, "run list": _GREEN_RUNS})))
        assert "no live assignments" not in text
        assert "unread (the mail could not be read: git for-each-ref failed)" in text
        assert "#7 lane/a [seat unread: the mail could not be read]" in text

    def test_a_failed_fetch_is_said(self, board, monkeypatch, tmp_path):
        """Dies to: fetch_mail's answer thrown away (stale refs under "read live")."""
        _stub_channel(monkeypatch, board, fetch=(False, "could not reach origin"))
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS})))
        assert "mail:     the fetch failed (could not reach origin)" in text

    def test_the_dispatchers_assignments_are_the_jobs(self, board, monkeypatch, tmp_path):
        mail = board.mail
        t = datetime(2026, 10, 9, 20, 0, 0, tzinfo=timezone.utc)
        job = mail.new_message("air", "assign", "", seat="win", lane="TP-479 wave B", ids=["TP-479"], now=t)
        self_made = mail.new_message("win-2", "assign", "", seat="win-2", lane="other", now=t)
        _stub_channel(monkeypatch, board, {"air": [job], "win-2": [self_made]})
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS})))
        assert ("jobs:     (dispatcher air) win: TP-479 wave B, TP-479 (since 2026-10-09T20:00:00Z; "
                f"assign {job['id']})") in text, "the release verb needs the assign id the board shows"
        assert "other" not in text, "only the dispatcher's assigns are jobs"

    def test_an_unusable_dispatcher_setting_is_named(self, board, monkeypatch, tmp_path):
        _stub_channel(monkeypatch, board, dispatcher=board.mail.DISPATCHER_UNUSABLE)
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS})))
        assert "jobs:     (the dispatcher setting is unusable: stubbed reason)" in text


_T0 = datetime(2026, 10, 14, 20, 0, 0, tzinfo=timezone.utc)
_NOW = datetime(2026, 10, 15, 2, 25, 0, tzinfo=timezone.utc)


class TestAsks:
    """TP-701 Wave A-1: the requests no ack names, oldest first with their
    ages: the dispatcher read them by hand from an ad-hoc census (2026-10-14).
    Paired on the request's id; A-0 item 2 found acks answering notes, acks
    and claims on the live record."""

    def _board(self, board, monkeypatch, tmp_path, by_machine, **kw):
        _stub_channel(monkeypatch, board, by_machine, **kw)
        return board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS}), now=_NOW)

    def test_the_line_lists_each_request_no_ack_names_with_its_age(self, board, monkeypatch, tmp_path):
        """The wave's red. Dies to: the ack pairing dropped (the answered
        request then appears)."""
        mail = board.mail
        answered = mail.new_message("win", "request", "a", lane="lane/a", now=_T0)
        open_ = mail.new_message("win-2", "request", "b", now=_T0.replace(minute=5))
        ack = mail.new_message("air", "ack", "done", ack=answered["id"], now=_T0.replace(minute=9))
        collected = self._board(board, monkeypatch, tmp_path, {"win": [answered], "win-2": [open_], "air": [ack]})
        assert [m["id"] for m in collected["asks"]] == [open_["id"]]
        text = board.render(collected)
        assert (f"asks:     1 open (requests no ack names, oldest first): {open_['id']} win-2 -: 6 h 20 min"
                in text), text
        assert answered["id"] not in text

    def test_each_row_carries_the_full_id_an_ack_must_name(self, board, monkeypatch, tmp_path):
        """The fold closes a request on its full id only, and an ack naming a
        six-character suffix is accepted and closes nothing, on an append-only
        record (failure-mode review, r1). Dies to: the row printing a suffix."""
        asked = board.mail.new_message("win", "request", "a", now=_T0)
        text = board.render(self._board(board, monkeypatch, tmp_path, {"win": [asked]}))
        row = next(ln for ln in text.splitlines() if ln.startswith("asks:"))
        assert f" {asked['id']} win -: " in row, row

    def test_the_line_names_the_lane_and_keeps_the_oldest_first(self, board, monkeypatch, tmp_path):
        mail = board.mail
        early = mail.new_message("win", "request", "a", lane="lane/a", now=_T0)
        late = mail.new_message("air", "request", "b", lane="lane/b", now=_T0.replace(hour=23))
        lines = board.render(self._board(board, monkeypatch, tmp_path, {"air": [late], "win": [early]})).splitlines()
        at = next(i for i, ln in enumerate(lines) if ln.startswith("asks:"))
        assert lines[at].endswith(f"{early['id']} win lane/a: 6 h 25 min")
        assert lines[at + 1] == f"          {late['id']} air lane/b: 3 h 25 min"

    def test_a_long_list_is_capped_with_a_count(self, board, monkeypatch, tmp_path):
        mail = board.mail
        asked = [mail.new_message("win", "request", f"r{i}", now=_T0.replace(minute=i)) for i in range(board.ASKS_SHOWN + 3)]
        lines = board.render(self._board(board, monkeypatch, tmp_path, {"win": asked})).splitlines()
        at = next(i for i, ln in enumerate(lines) if ln.startswith("asks:"))
        assert lines[at].startswith(f"asks:     {board.ASKS_SHOWN + 3} open")
        assert lines[at + board.ASKS_SHOWN] == "          and 3 more"

    def test_none_open_and_unread_mail_read_differently(self, board, monkeypatch, tmp_path):
        """Dies to: an unread mail printed as "none open", which reads as an answer."""
        text = board.render(self._board(board, monkeypatch, tmp_path, {}))
        assert "asks:     none open (every request has an ack naming it)" in text
        text = board.render(self._board(board, monkeypatch, tmp_path, {}, read_error="git for-each-ref failed"))
        assert "asks:     unread (the mail could not be read: git for-each-ref failed)" in text
        assert "none open" not in text


def _registry(tmp_path: Path, *cwds: Path) -> Path:
    """A scratch Claude Code session registry: one entry per cwd, every pid
    this process's own (alive), each its own session id (``0000000<i>-...``)."""
    import os

    config = tmp_path / "claude-config"
    (config / "sessions").mkdir(parents=True)
    for i, cwd in enumerate(cwds):
        (config / "sessions" / f"{i}.json").write_text(
            json.dumps({"pid": os.getpid(), "sessionId": f"{i:08d}-aaaa", "cwd": str(cwd)}), encoding="utf-8")
    return config


def _git_for(main: Path, *worktrees: Path, clone: str | None = "air", names: dict | None = None):
    """A runner answering the git reads the seats line makes: this clone's
    checkouts (``worktree list --porcelain``), the clone's machine name, and
    the name each checkout answers (``config --get`` with it as cwd; by
    default the clone's for the main checkout and ``<clone>-<directory>``,
    SessionStart's naming, for a worktree)."""
    if names is None:
        names = {str(main): clone, **{str(w): f"{clone}-{w.name}" for w in worktrees}} if clone else {}

    def run(argv, **kw):
        if argv[1:3] == ["worktree", "list"]:
            blocks = [f"worktree {main}\nHEAD {'1' * 40}\nbranch refs/heads/main\n"]
            blocks += [f"worktree {w}\nHEAD {'2' * 40}\nbranch refs/heads/lane/{w.name}\n" for w in worktrees]
            return 0, "\n".join(blocks), ""
        if argv[1:3] == ["config", "--local"]:
            return (0, clone + "\n", "") if clone else (1, "", "")
        if argv[1:3] == ["config", "--get"]:
            name = names.get(str(kw.get("cwd")))
            return (0, name + "\n", "") if name else (1, "", "")
        raise AssertionError(f"unexpected call {argv}")
    return run


class TestSeats:
    """TP-701 Wave A-2: one row per seat. A remote seat is its last mail and
    nothing more (the channel is all the board can read about another
    machine); this clone's checkouts carry their live sessions from Claude
    Code's own registry, and two in one checkout are flagged: the state the
    win-2 relaunch reached on 2026-10-15 02:00Z, caught only by a seat
    reading its banner."""

    def _clone(self, tmp_path):
        main = tmp_path / "repo"
        work = main / ".claude" / "worktrees" / "work"
        work.mkdir(parents=True)
        return main, work

    def _seats(self, board, main, work, config, by_machine=None, *more, names=None):
        local = board.read_sessions(main, run_=_git_for(main, work, *more, names=names), config_dir=config,
                                    inside_session=False)
        return board.seat_rows(by_machine or {}, local, _NOW), local

    def _text(self, board, rows, unread="", **extra):
        return board.render({"seats": {"rows": rows, "unread": unread, "checked": True, **extra}})

    def test_a_hand_named_worktree_is_the_seat_it_answers(self, board, tmp_path):
        """The protocol's own recipe names a worktree by hand, and SessionStart
        refuses a derived name another worktree holds; the seat is the name
        the checkout answers, which its mail ref is written under. Dies to: the
        name derived from the directory (both reviewers, r1)."""
        main, work = self._clone(tmp_path)
        claim = board.mail.new_message("air-w2", "claim", "", lane="lane/x", now=_T0.replace(hour=23, minute=25))
        rows, _ = self._seats(board, main, work, _registry(tmp_path, work), {"air-w2": [claim]},
                              names={str(main): "air", str(work): "air-w2"})
        text = self._text(board, rows)
        assert "air-w2: last mail 3 h 0 min ago (claim); 1 live session in .claude/worktrees/work" in text, text
        assert "air-work" not in text

    def test_two_checkouts_answering_one_name_keep_both_and_say_so(self, board, tmp_path):
        """A worktree with no name of its own answers its clone's, and two
        directories can derive one name: the second never overwrites the
        first's row (a live session vanished under that, r1). Dies to: the
        rows keyed by name alone."""
        main, work = self._clone(tmp_path)
        note = board.mail.new_message("air", "note", "x", now=_T0)
        rows, _ = self._seats(board, main, work, _registry(tmp_path, work), {"air": [note]},
                              names={str(main): "air", str(work): "air"})
        text = self._text(board, rows)
        assert "air: last mail 6 h 25 min ago (note); no live session in the main checkout" in text, text
        assert ("air [.claude/worktrees/work]: the seat name of the main checkout too (one mail ref for both); "
                "1 live session in .claude/worktrees/work") in text, text
        work2 = main / ".claude" / "worktrees" / "work2"
        work2.mkdir()
        first_only, _ = self._seats(board, main, work, _registry(tmp_path / "b", work), None, work2,
                                    names={str(main): "air", str(work): "air-x", str(work2): "air-x"})
        assert "air-x: no mail; 1 live session in .claude/worktrees/work" in self._text(board, first_only)

    def test_a_flagged_checkout_names_its_sessions(self, board, tmp_path):
        """The registry lists headless and editor sessions too, so the flag
        names each by pid and session id before anyone closes one. Dies to:
        a bare count."""
        import os

        main, work = self._clone(tmp_path)
        rows, _ = self._seats(board, main, work, _registry(tmp_path, work, work))
        text = self._text(board, rows)
        assert f"(pid {os.getpid()} session 00000000, pid {os.getpid()} session 00000001)" in text, text

    def test_a_quiet_seat_folds_into_a_count(self, board, tmp_path):
        """A seat name outlives its worktree, so a row per name ever used grows
        without end. Dies to: every quiet seat printed."""
        main, work = self._clone(tmp_path)
        old = board.mail.new_message("air-gone", "release", "", lane="lane/x", now=datetime(2026, 10, 7, 0, 0, 0,
                                                                                           tzinfo=timezone.utc))
        recent = board.mail.new_message("win", "note", "x", now=_T0)
        rows, _ = self._seats(board, main, work, _registry(tmp_path), {"air-gone": [old], "win": [recent]})
        text = self._text(board, rows)
        assert "air-gone" not in text and "win: last mail" in text, text
        assert f"and 1 seat with no mail in {board.SEAT_QUIET_DAYS} d and no live session here" in text, text

    def test_outside_a_session_the_registry_read_says_it_is_unchecked(self, board, tmp_path):
        """Run from a plain terminal, the own-entry check cannot run, so an
        empty reading of another config directory would read as no session
        (failure-mode review, r1). Dies to: the absence stated bare."""
        main, work = self._clone(tmp_path)
        rows, local = self._seats(board, main, work, _registry(tmp_path, work))
        assert local["checked"] is False
        text = board.render({"seats": {"rows": rows, "unread": "", "checked": False, "registry": local["registry"]}})
        assert "run outside a session, so not checked against one" in text, text

    def test_an_unread_mail_never_reads_as_no_seats(self, board, monkeypatch, tmp_path):
        """The asks line's own rule, carried over (code review, r1). Dies to:
        the empty-state sentence printed under an unread mail."""
        _stub_channel(monkeypatch, board, read_error="git for-each-ref failed")
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS}), now=_NOW))
        assert "seats:    other seats unread (the mail could not be read: git for-each-ref failed)" in text, text
        assert "no machine has mail" not in text

    def test_collect_joins_the_mail_and_the_local_read(self, board, monkeypatch, tmp_path):
        """The wiring, not only the parts (failure-mode review, r1). Dies to:
        an empty mail fold or the local unread reason dropped in collect."""
        note = board.mail.new_message("win", "note", "x", now=_T0)
        local = {"checkouts": [{"path": str(tmp_path), "main": True, "seat": "win",
                                "sessions": [{"pid": 7, "session_id": "abcdef0123"}]}], "unread": "", "checked": True}
        _stub_channel(monkeypatch, board, {"win": [note]}, sessions=local)
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS}), now=_NOW))
        assert "seats:    win: last mail 6 h 25 min ago (note); 1 live session in the main checkout" in text, text
        _stub_channel(monkeypatch, board, {"win": [note]}, sessions={"checkouts": [], "unread": "registry gone"})
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS}), now=_NOW))
        assert "          live sessions here unread: registry gone" in text, text

    def test_a_seats_read_that_raises_costs_only_its_line(self, board, monkeypatch, tmp_path):
        """Each section is read on its own. Dies to: an exception other than
        Unresolvable taking the whole board down."""
        _stub_channel(monkeypatch, board)

        def broken(root, **kw):
            raise RuntimeError("a registry shape nobody planned for")

        monkeypatch.setattr(board, "read_sessions", broken)
        collected = board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS}), now=_NOW)
        assert "RuntimeError: a registry shape nobody planned for" in collected["seats"]["unread"]
        assert "post-merge proof green" in board.render(collected)

    def test_ages_read_plainly_at_both_ends(self, board):
        assert board._age(30) == "under 1 min" and board._age(2 * 86400 + 3 * 3600 + 59) == "2 d 3 h"
        row = {"seat": "win", "last_mail": {"type": "note", "age_s": None}, "sessions": None}
        assert board._seat_line(row, False) == "win: last mail at an unread time (note)"

    def test_two_sessions_in_one_checkout_are_flagged_and_one_is_not(self, board, tmp_path):
        """The wave's red. Dies to: the grouping by checkout dropped, so two
        sessions in one checkout read as two seats."""
        main, work = self._clone(tmp_path)
        rows, _ = self._seats(board, main, work, _registry(tmp_path, work, work))
        [row] = rows
        assert row["seat"] == "air-work" and len(row["sessions"]) == 2 and row["shared"] is True
        text = board.render({"seats": {"rows": rows, "unread": ""}})
        assert "seats:    air-work: no mail; 2 live sessions in .claude/worktrees/work (pid " in text, text
        assert "): TWO SESSIONS IN ONE CHECKOUT" in text, text
        single, _ = self._seats(board, main, work, _registry(tmp_path / "one", work))
        assert single[0]["shared"] is False and "TWO SESSIONS" not in board.render({"seats": {"rows": single}})

    def test_a_session_counts_for_the_deepest_checkout_that_holds_it(self, board, tmp_path):
        """A worktree sits inside the main checkout's folder, so a prefix test
        alone would count its session for both. Dies to: the first matching
        checkout taken instead of the deepest."""
        main, work = self._clone(tmp_path)
        (work / "sub").mkdir()
        rows, _ = self._seats(board, main, work, _registry(tmp_path, main, work / "sub"))
        by_seat = {r["seat"]: r for r in rows}
        assert len(by_seat["air"]["sessions"]) == 1 and by_seat["air"]["checkout"] == "the main checkout"
        assert len(by_seat["air-work"]["sessions"]) == 1 and not by_seat["air-work"]["shared"]

    def test_a_remote_seat_is_its_last_mail_and_never_live_or_dead(self, board, tmp_path):
        """Dies to: a remote row worded as liveness the channel cannot support."""
        main, work = self._clone(tmp_path)
        mail = board.mail
        first = mail.new_message("win", "note", "x", now=_T0)
        last = mail.new_message("win", "claim", "", lane="lane/x", now=_T0.replace(hour=23, minute=25))
        rows, _ = self._seats(board, main, work, _registry(tmp_path, work), {"win": [first, last]})
        text = board.render({"seats": {"rows": rows, "unread": ""}})
        row = next(ln for ln in text.splitlines() if "win:" in ln)
        assert row.endswith("win: last mail 3 h 0 min ago (claim)"), row
        assert "live" not in row and "dead" not in row

    def test_a_local_seat_joins_its_mail_and_its_sessions(self, board, tmp_path):
        main, work = self._clone(tmp_path)
        note = board.mail.new_message("air", "note", "x", now=_T0.replace(hour=23, minute=25))
        rows, _ = self._seats(board, main, work, _registry(tmp_path, work), {"air": [note]})
        text = board.render({"seats": {"rows": rows, "unread": ""}})
        assert "air: last mail 3 h 0 min ago (note); no live session in the main checkout" in text, text
        assert "air-work: no mail; 1 live session in .claude/worktrees/work" in text, text

    def test_an_unreadable_registry_is_unread_never_no_session(self, board, tmp_path):
        """Dies to: a registry that cannot be read in full rendered as "no live
        session" (live_sessions answers None for it, Assumption 6)."""
        main, work = self._clone(tmp_path)
        empty = tmp_path / "no-registry"
        empty.mkdir()
        note = board.mail.new_message("air", "note", "x", now=_T0)
        rows, local = self._seats(board, main, work, empty, {"air": [note]})
        assert "registry" in local["unread"]
        text = board.render({"seats": {"rows": rows, "unread": local["unread"]}})
        assert "no live session" not in text and "live sessions here unread" in text, text

    def test_a_registry_that_does_not_list_this_session_is_unread(self, board, tmp_path):
        """Run from inside a session, the registry must list it, or it is not
        the registry this session writes to (checkout_sync.main's own check)."""
        main, work = self._clone(tmp_path)
        local = board.read_sessions(main, run_=_git_for(main, work), config_dir=_registry(tmp_path, work),
                                    inside_session=True)
        assert "does not list this session" in local["unread"]

    def test_a_session_outside_this_clone_is_not_named(self, board, tmp_path):
        main, work = self._clone(tmp_path)
        elsewhere = tmp_path / "other-repo"
        elsewhere.mkdir()
        rows, _ = self._seats(board, main, work, _registry(tmp_path, elsewhere))
        assert rows == []

    def test_the_json_carries_both_new_keys(self, board, monkeypatch, tmp_path):
        """The pass criterion: `board.py --json` carries asks and seats, and no
        key an older reader keys on is gone."""
        _stub_channel(monkeypatch, board)
        collected = board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS}), now=_NOW)
        assert {"asks", "seats", "open_prs", "post_merge", "assignments", "claims"} <= set(collected)
        json.dumps(collected)


class TestDerivedNotRestated:
    @pytest.mark.contract
    def test_the_ledger_count_is_the_generators(self, board, monkeypatch, tmp_path):
        """The count comes from the generator's own parser over the view, never a
        second one. The scratch tree carries the row files: since the fold
        (2026-10-14) the ledger file alone holds no row, and the comparison read
        0 against 0 (review, 2026-10-14)."""
        import shutil

        packs = tmp_path / "task-packs"
        packs.mkdir(parents=True)
        shutil.copy(REPO_ROOT / "task-packs" / "FORWARD_LEDGER.md", packs / "FORWARD_LEDGER.md")
        if (REPO_ROOT / "task-packs" / "ledger.d").is_dir():
            shutil.copytree(REPO_ROOT / "task-packs" / "ledger.d", packs / "ledger.d")
        gen = _load("generate_ledger_regions", "gen_for_board_test")
        expected = len(gen.live_member_ids(gen.record_fragments().ledger_text(tmp_path)))
        assert expected >= 100, f"the scratch ledger reads {expected} live rows: the copy or the view broke"
        assert board.read_ledger_live(tmp_path) == expected
        assert board.read_ledger_live(tmp_path / "nowhere") is None

    def test_the_workflow_and_the_red_set_are_the_ship_drivers(self, board):
        """One name for the post-merge proof and one set of red conclusions."""
        ship = _load("ship", "ship_for_board_test")
        assert board.POST_MERGE_WORKFLOW == ship.POST_MERGE_WORKFLOW
        assert board._RED == ship.POST_MERGE_RED
