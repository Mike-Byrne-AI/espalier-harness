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


def _stub_channel(monkeypatch, board, by_machine=None, dispatcher="air", fetch=(True, ""), read_error=None):
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
        assert "jobs:     (dispatcher air) win: TP-479 wave B, TP-479 (since 2026-10-09T20:00:00Z)" in text
        assert "other" not in text, "only the dispatcher's assigns are jobs"

    def test_an_unusable_dispatcher_setting_is_named(self, board, monkeypatch, tmp_path):
        _stub_channel(monkeypatch, board, dispatcher=board.mail.DISPATCHER_UNUSABLE)
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS})))
        assert "jobs:     (the dispatcher setting is unusable: stubbed reason)" in text


class TestDerivedNotRestated:
    @pytest.mark.contract
    def test_the_ledger_count_is_the_generators(self, board, monkeypatch, tmp_path):
        """The count comes from the generator's own parser, never a second one."""
        ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
        ledger.parent.mkdir(parents=True)
        ledger.write_text((REPO_ROOT / "task-packs" / "FORWARD_LEDGER.md").read_text(encoding="utf-8"),
                          encoding="utf-8")
        gen = _load("generate_ledger_regions", "gen_for_board_test")
        expected = len(gen.live_member_ids(ledger.read_text(encoding="utf-8")))
        assert board.read_ledger_live(tmp_path) == expected
        assert board.read_ledger_live(tmp_path / "nowhere") is None

    def test_the_workflow_and_the_red_set_are_the_ship_drivers(self, board):
        """One name for the post-merge proof and one set of red conclusions."""
        ship = _load("ship", "ship_for_board_test")
        assert board.POST_MERGE_WORKFLOW == ship.POST_MERGE_WORKFLOW
        assert board._RED == ship.POST_MERGE_RED
