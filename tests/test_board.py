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
from tests._live_tree import copy_checkout

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
    global _REAL_SECTION
    module = _load("board", "board_under_test")
    _REAL_SECTION = module.read_overlaps_section   # the real one, for rows that undo _stub_channel's
    return module


_REAL_SECTION = None


def _gh(answers: dict[str, object]):
    """A runner answering ``gh`` by its first words (``pr list``, ``run list``,
    ``api compare``); anything else is an unexpected call."""
    calls: list[list[str]] = []

    def run(argv, **kw):
        calls.append(list(argv))
        key = " ".join(argv[1:3]) if argv[1] != "api" else ("api compare" if "/compare/" in argv[2] else argv[2])
        if key == "pr list" and "merged" in argv:
            # The checks: line's read; a fixture that gives none reads no merges,
            # so the open-PR answer is never mistaken for the merged listing.
            key = "pr list merged"
            if key not in answers:
                return 0, "[]", ""
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
    # The records refs' fetch beside the mail's: the parked rows the records
    # section reads; TestRecordsLine drives a failed one.
    monkeypatch.setattr(board.mail, "fetch_records", lambda root, run=None: (True, ""))

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
    # The overlaps section's fetch and symbol reads; TestOverlapsSection drives the real one.
    monkeypatch.setattr(board, "read_overlaps_section", lambda *a, **k: {"pairs": [], "notes": []})
    # The records section's two git reads beside the base's tree: the names the
    # base's history deleted and the names on the open pull requests' heads;
    # TestRecordsLine stands each in by name.
    monkeypatch.setattr(board, "read_pruned_names", lambda root, base, **k: [])
    monkeypatch.setattr(board, "read_riding_names", lambda root, prs, seat_of, **k: [])
    # The base fetch and the ledger count at the base: git and a child
    # interpreter, which tests/test_board_ledger_base.py drives for real.
    monkeypatch.setattr(board, "fetch_base", lambda *a, **k: (True, ""))
    monkeypatch.setattr(board, "read_ledger_at_base", lambda *a, **k: None)
    # The records section's reads of the Session Log names: the base's (git
    # ls-tree) and the rows parked on the records refs (mail.pending), which
    # TestRecordsLine drives with names of its own and the first for real.
    monkeypatch.setattr(board, "read_row_names", lambda *a, **k: [])
    monkeypatch.setattr(board.mail, "pending", lambda root, directory, against, **k: [])


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

    def test_a_release_names_a_lane_only_from_a_seat_that_claimed_it(self, board):
        """The dispatcher closes a job by lane after the seat's push released
        the claim; its release is the lane's latest message and moved the
        lane, its debt and its open pull request onto the dispatcher (TP-703d's
        predicted defect, reproduced at its review). A release counts only
        from a machine with an earlier claim on that lane; a lane only ever
        released is nobody's. Dies to: the latest message taken whoever sent it."""
        mail = board.mail
        t = datetime(2026, 10, 9, 20, 0, 0, tzinfo=timezone.utc)
        claim = mail.new_message("win", "claim", "", lane="lane/x", now=t)
        shipped = mail.new_message("win", "release", "", lane="lane/x", now=t.replace(minute=5))
        closed = mail.new_message("air", "release", "", lane="lane/x", now=t.replace(minute=9))
        stray = mail.new_message("air", "release", "", lane="lane/y", now=t.replace(minute=9))
        assert mail.lane_seats({"win": [claim, shipped], "air": [closed, stray]}) == {"lane/x": "win"}
        taken = mail.new_message("air", "claim", "", lane="lane/x", now=t.replace(minute=20))
        assert mail.lane_seats({"win": [claim, shipped], "air": [closed, taken]}) == {"lane/x": "air"}


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

    def test_a_pull_request_no_claim_names_shows_the_seat_its_label_names(self, board, monkeypatch, tmp_path):
        """DEF-4044: the seat label the ship driver stamps names a lane no claim
        does, here as on the records line and in the overlap notice; a claim
        still wins, and the open-PR read asks for the labels. Dies to: the
        label ignored at this sister site, read over a claim, or never read."""
        claim = board.mail.new_message("win-2", "claim", "", lane="lane/b")
        _stub_channel(monkeypatch, board, {"win-2": [claim]})
        prs = [{"number": 7, "headRefName": "lane/a", "mergeStateStatus": "CLEAN", "isDraft": False,
                "autoMergeRequest": None, "labels": [{"name": "python"}, {"name": "seat:win"}]},
               {"number": 8, "headRefName": "lane/b", "mergeStateStatus": "CLEAN", "isDraft": False,
                "autoMergeRequest": None, "labels": [{"name": "seat:win"}]}]
        run = _gh({"pr list": prs, "run list": _GREEN_RUNS})
        collected = board.collect(tmp_path, run_=run, now=_NOW)
        assert [pr["seat"] for pr in collected["open_prs"]] == ["win", "win-2"]
        text = board.render(collected)
        assert "#7 lane/a [win]:" in text and "#8 lane/b [win-2]:" in text, text
        reads = [c for c in run.calls if c[:3] == ["gh", "pr", "list"] and "open" in c]
        assert reads and "labels" in reads[0][reads[0].index("--json") + 1]

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
        """A red run carries several merges when a run between it and the last
        green one was red, still going or cancelled: naming the newest as the
        culprit would revert an innocent seat's work. Dies to: a revert printed
        for one of several suspects."""
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
        assert "a newer run is going" not in text, "no run is in flight here"

    def test_a_run_still_going_between_the_red_and_the_last_green_is_named(self, board, monkeypatch, tmp_path):
        """Overlapping runs finish out of order: an older run can still be going
        under a red verdict, and its result can narrow the suspects. Dies to: a
        run between the red and the green read as nothing, or as newer."""
        _stub_channel(monkeypatch, board)
        mid = "c0ffee1" + "0" * 33
        runs = [_run("completed", "failure", RED_SHA), _run("in_progress", "", mid),
                _run("completed", "success", GREEN_SHA)]
        run = _gh({"pr list": [], "run list": runs,
                   "api compare": {"commits": [_merge(41, "1" * 40), _merge(42, "2" * 40)]}})
        text = board.render(board.collect(tmp_path, run_=run))
        assert "suspects #41, #42" in text
        assert "a run between it and the last green is still going (on c0ffee1)" in text
        assert "a newer run is going" not in text

    def test_a_red_beside_a_newer_run_in_flight_says_so(self, board, monkeypatch, tmp_path):
        """Runs overlap now (DEF-2015: no newer push cancels an older one), so a
        red usually has a newer tip's proof going beside it, which the green line
        already says. Dies to: the red line rendered without the running flag."""
        _stub_channel(monkeypatch, board)
        run = _gh({"pr list": [], "run list": _RED_THEN_GREEN,
                   "api compare": {"commits": [_merge(41, "1" * 40), _merge(42, "2" * 40)]}})
        text = board.render(board.collect(tmp_path, run_=run))
        assert "suspects #41, #42" in text and "a newer run is going, and its verdict will supersede this one" in text

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


_POST_MERGE_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "post_merge"


def _merged_rollups() -> list[dict]:
    """The frozen #312/#313 rollups: the Windows leg red on #313 and green on
    #312 from a run that finished after #313 merged; the macOS leg red on both."""
    return [json.loads((_POST_MERGE_FIXTURES / f"pr{n}.json").read_text(encoding="utf-8")) for n in (313, 312)]


def _with_leg(pr: dict, name: str, **fields) -> dict:
    out = json.loads(json.dumps(pr))
    for row in out["statusCheckRollup"]:
        if row.get("name") == name:
            row.update(fields)
    return out


class TestChecksLine:
    """The board's `checks:` line: each check whose owned verdict over the last
    RUN_WINDOW merged pull requests is red, with the merge it went red on, the
    leg's finish and what stands beside it, read through tools/cc/_post_merge.py
    (the rule the banner and the ship preflight read too). The Windows red of
    2026-10-18 sat unread for six hours because no board line carried it."""

    def test_the_line_names_the_red_with_its_merge_and_the_green_on(self, board, monkeypatch, tmp_path):
        """Dies to: the merged listing not read, the since clause or the green-on
        clause dropped, or the macOS red given a false origin."""
        _stub_channel(monkeypatch, board)
        run = _gh({"pr list": [], "pr list merged": _merged_rollups(), "run list": _GREEN_RUNS})
        collected = board.collect(tmp_path, run_=run)
        text = board.render(collected)
        assert ("checks:   new: portability (windows-latest): red since #313 (merged 2026-10-18 13:26Z, "
                "the leg finished 13:57Z), green on #312") in text   # new: on this checkout's first read
        assert "          portability (macos-latest): red since #312 or earlier (the oldest merge read)" in text
        assert collected["post_merge_checks"]["window"] == 2 and collected["post_merge_checks"]["logged"] == 1
        reads = [c for c in run.calls if c[1:3] == ["pr", "list"]]
        rollups = [c for c in reads if "merged" in c and "statusCheckRollup" in c[c.index("--json") + 1]]
        assert len(reads) == 3 and len(rollups) == 1, "one rollup read for this line beside the records line's lane read and the open one"

    def test_a_cancelled_latest_run_is_no_verdict_beside_the_red_never_green(self, board, monkeypatch, tmp_path):
        """Dies to: a cancelled run read as a verdict, or not named."""
        _stub_channel(monkeypatch, board)
        rows = _merged_rollups()
        newer = _with_leg(rows[0], "portability (windows-latest)", conclusion="CANCELLED",
                          startedAt="2026-10-18T14:30:00Z", completedAt="2026-10-18T14:31:00Z")
        newer.update(number=320, mergedAt="2026-10-18T15:00:00Z")
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "pr list merged": [newer, *rows],
                                                              "run list": _GREEN_RUNS})))
        assert "portability (windows-latest): red since #313" in text and "#320 no verdict (cancelled)" in text

    def test_all_green_says_none_red(self, board, monkeypatch, tmp_path):
        _stub_channel(monkeypatch, board)
        rows = [_with_leg(_with_leg(pr, "portability (windows-latest)", conclusion="SUCCESS"),
                          "portability (macos-latest)", conclusion="SUCCESS") for pr in _merged_rollups()]
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "pr list merged": rows,
                                                              "run list": _GREEN_RUNS})))
        assert "checks:   none red among the last 2 merges" in text

    def test_a_first_mention_is_logged_once_and_a_failed_append_is_a_note(self, board, monkeypatch, tmp_path):
        """The roadmap's red-to-first-mention figure is derived from this log.
        Dies to: a transition logged on every read, or a failed append taking
        the line down."""
        _stub_channel(monkeypatch, board)
        answers = {"pr list": [], "pr list merged": _merged_rollups(), "run list": _GREEN_RUNS}
        board.collect(tmp_path, run_=_gh(answers))
        log = tmp_path / board.CHECKS_LOG
        first = log.read_text(encoding="utf-8").splitlines()
        assert len(first) == 1 and json.loads(first[0])["since_pr"] == 313   # the macOS red predates the window
        second = board.collect(tmp_path, run_=_gh(answers))
        assert log.read_text(encoding="utf-8").splitlines() == first and second["post_merge_checks"]["logged"] == 0
        log.unlink()
        log.mkdir()   # a path that cannot be appended to
        text = board.render(board.collect(tmp_path, run_=_gh(answers)))
        assert "checks:   portability (windows-latest): red since #313" in text
        assert "the transitions log could not be written" in text

    def test_a_red_older_than_the_window_is_never_a_first_mention(self, board, monkeypatch, tmp_path):
        """The window slides with every merge: a persistent red would otherwise
        log a false first mention per merge. Dies to: the origin-unknown red
        logged, or logged again when the window moves."""
        _stub_channel(monkeypatch, board)
        rows = _merged_rollups()
        board.collect(tmp_path, run_=_gh({"pr list": [], "pr list merged": rows, "run list": _GREEN_RUNS}))
        log = tmp_path / board.CHECKS_LOG
        first = log.read_text(encoding="utf-8").splitlines()
        assert len(first) == 1 and json.loads(first[0])["check"] == "portability (windows-latest)"
        newer = _with_leg(rows[0], "portability (windows-latest)", conclusion="FAILURE",
                          startedAt="2026-10-18T14:30:00Z", completedAt="2026-10-18T15:00:00Z")
        newer.update(number=320, mergedAt="2026-10-18T15:00:00Z")
        slid = board.collect(tmp_path, run_=_gh({"pr list": [], "pr list merged": [newer, rows[0]], "run list": _GREEN_RUNS}))
        assert log.read_text(encoding="utf-8").splitlines() == first and slid["post_merge_checks"]["logged"] == 0

    def test_a_first_mention_is_marked_new_on_that_read_only(self, board, monkeypatch, tmp_path):
        _stub_channel(monkeypatch, board)
        answers = {"pr list": [], "pr list merged": _merged_rollups(), "run list": _GREEN_RUNS}
        first = board.render(board.collect(tmp_path, run_=_gh(answers)))
        assert "checks:   new: portability (windows-latest): red since #313" in first
        second = board.render(board.collect(tmp_path, run_=_gh(answers)))
        assert "checks:   portability (windows-latest): red since #313" in second and "new:" not in second

    def test_a_check_with_no_verdict_on_any_merge_is_named_never_green(self, board, monkeypatch, tmp_path):
        _stub_channel(monkeypatch, board)
        rows = [_with_leg(_with_leg(pr, "portability (windows-latest)", conclusion="CANCELLED"),
                          "portability (macos-latest)", conclusion="SUCCESS") for pr in _merged_rollups()]
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "pr list merged": rows,
                                                              "run list": _GREEN_RUNS})))
        assert "checks:   portability (windows-latest): no verdict on every merge read (cancelled)" in text
        assert "none red" not in text

    def test_an_unread_listing_costs_only_the_checks_line(self, board, monkeypatch, tmp_path):
        """Dies to: the merged read's failure taking another section down."""
        _stub_channel(monkeypatch, board)
        run = _gh({"pr list": [], "pr list merged": board.Unresolvable("gh pr list answered rc=1 with no JSON: x"),
                   "run list": _GREEN_RUNS})
        text = board.render(board.collect(tmp_path, run_=run))
        assert "checks:   unread (gh pr list answered rc=1 with no JSON: x)" in text
        assert "open PRs: none" in text and "main:     post-merge proof green on aaaaaaa" in text


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
        assert ("jobs:     (dispatcher air) 1 live: win: TP-479 wave B, TP-479 (since 2026-10-09T20:00:00Z; "
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

    def test_the_header_counts_the_operator_calls_apart(self, board, monkeypatch, tmp_path):
        """TP-703d: the dispatcher's question to the operator rides the channel
        as a request opening with the prefix, so every seat's board lists it
        with an age; the header counts those apart. Dies to: the prefix read
        on a note, or the count printed when no request carries it."""
        mail = board.mail
        calls = [mail.new_message("air", "request", f"{mail.OPERATOR_CALL_PREFIX} 703c on the Mac or the win box?",
                                  now=_T0),
                 mail.new_message("air", "request", f"  {mail.OPERATOR_CALL_PREFIX} a fifth seat?", now=_T0.replace(minute=1))]
        plain = mail.new_message("win", "request", "which base?", lane="lane/a", now=_T0.replace(minute=2))
        note = mail.new_message("win-2", "note", f"{mail.OPERATOR_CALL_PREFIX} not a request", now=_T0)
        text = board.render(self._board(board, monkeypatch, tmp_path, {"air": calls, "win": [plain], "win-2": [note]}))
        assert "asks:     3 open, 2 operator calls (requests no ack names, oldest first): " in text, text
        rows = [ln for ln in text.splitlines() if calls[0]["id"] in ln or calls[1]["id"] in ln or plain["id"] in ln]
        assert [ln.endswith(" (operator call)") for ln in rows] == [True, True, False], rows
        text = board.render(self._board(board, monkeypatch, tmp_path, {"win": [plain]}))
        assert "asks:     1 open (requests no ack names, oldest first): " in text, text
        assert "operator call" not in text
        # The count is over every open ask, not the rows shown: the call last.
        many = [mail.new_message("win", "request", f"r{i}", now=_T0.replace(minute=i)) for i in range(board.ASKS_SHOWN)]
        last = mail.new_message("air", "request", f"{mail.OPERATOR_CALL_PREFIX} last", now=_T0.replace(minute=30))
        text = board.render(self._board(board, monkeypatch, tmp_path, {"win": many, "air": [last]}))
        assert f"asks:     {board.ASKS_SHOWN + 1} open, 1 operator call (requests" in text, text

    def test_the_header_counts_the_stops_apart_and_tags_the_row(self, board, monkeypatch, tmp_path):
        """DEF-5030 (2026-10-30): a worker's stop rides the channel as a
        request opening with ``stopped:`` (the worker tick's STOP clause), so
        the dispatcher's past-the-hour gridlock read is the row's age; the
        header counts the stops apart beside the operator calls and the row
        says which it is. Dies to: a stop counted as a plain ask, the prefix
        read on a note, or the count printed with no stop open."""
        mail = board.mail
        stop = mail.new_message("win", "request", f"{mail.STOPPED_PREFIX} a conflict outside my files, docs/HOOKS.md",
                                lane="lane/a", now=_T0)
        call = mail.new_message("air", "request", f"{mail.OPERATOR_CALL_PREFIX} a fifth seat?", now=_T0.replace(minute=1))
        plain = mail.new_message("win-2", "request", "which base?", lane="lane/b", now=_T0.replace(minute=2))
        note = mail.new_message("win-2", "note", f"{mail.STOPPED_PREFIX} not a request", now=_T0)
        text = board.render(self._board(board, monkeypatch, tmp_path, {"win": [stop], "air": [call], "win-2": [plain, note]}))
        assert "asks:     3 open, 1 stopped, 1 operator call (requests no ack names, oldest first): " in text, text
        rows = [ln for ln in text.splitlines() if stop["id"] in ln or call["id"] in ln or plain["id"] in ln]
        assert [ln.endswith(" (stopped)") for ln in rows] == [True, False, False], rows
        assert rows[0].endswith(f"{stop['id']} win lane/a: 6 h 25 min (stopped)"), rows
        second = mail.new_message("win-2", "request", f"{mail.STOPPED_PREFIX} the guard refuses the edit",
                                  lane="lane/b", now=_T0.replace(minute=3))
        text = board.render(self._board(board, monkeypatch, tmp_path, {"win": [stop], "win-2": [second]}))
        assert "asks:     2 open, 2 stopped (requests no ack names, oldest first): " in text, text
        text = board.render(self._board(board, monkeypatch, tmp_path, {"win-2": [plain, note]}))
        assert "asks:     1 open (requests no ack names, oldest first): " in text, text
        assert " stopped" not in text and "(stopped)" not in text

    def test_none_open_and_unread_mail_read_differently(self, board, monkeypatch, tmp_path):
        """Dies to: an unread mail printed as "none open", which reads as an answer."""
        text = board.render(self._board(board, monkeypatch, tmp_path, {}))
        assert "asks:     none open (every request has an ack naming it)" in text
        text = board.render(self._board(board, monkeypatch, tmp_path, {}, read_error="git for-each-ref failed"))
        assert "asks:     unread (the mail could not be read: git for-each-ref failed)" in text
        assert "none open" not in text


class TestRecordsLine:
    """TP-703d: each seat with a checkout here, a live claim, a job or a lane
    merged in the window shows its lanes merged since its newest Session Log
    row on the BASE or parked on its records ref (three seats merged 2 to 11
    lanes a day with no row, 2026-10-16 to 10-17, and nothing said so). The
    count is the loader's own (``lanes_since_row``), the one the ship driver's
    row-debt read shares, over the one merged read's lane fields."""

    # Noon UTC: the same local day in every zone a seat runs in.
    _LANES = [{"number": 1, "headRefName": "lane/a", "mergedAt": "2026-10-19T12:00:00Z"},
              {"number": 2, "headRefName": "lane/b", "mergedAt": "2026-10-18T12:00:00Z"},
              {"number": 3, "headRefName": "lane/c", "mergedAt": "2026-10-20T12:00:00Z"},
              {"number": 4, "headRefName": "lane/d", "mergedAt": "2026-10-20T12:00:00Z"}]
    _NAMES = ["memory/session-log.d/2026-10-15-073941-win.md", "memory/session-log.d/2026-10-18-163553-win.md",
              "memory/session-log.d/2026-10-19-053029-air.md"]

    def _channel(self, board):
        mail = board.mail
        return {"win": [mail.new_message("win", "claim", "", lane="lane/a", paths=["a.py"], now=_T0),
                        mail.new_message("win", "claim", "", lane="lane/b", paths=["b.py"], now=_T0),
                        mail.new_message("win", "release", "", lane="lane/b", now=_T0.replace(minute=1))],
                "win-2": [mail.new_message("win-2", "claim", "", lane="lane/c", paths=["c.py"], now=_T0)],
                # air-work shipped lane/d (claimed, then released by its push) and
                # holds nothing live; air only ever released lane/x and is quiet.
                "air-work": [mail.new_message("air-work", "claim", "", lane="lane/d", paths=["d.py"], now=_T0),
                             mail.new_message("air-work", "release", "", lane="lane/d", now=_T0.replace(minute=2))],
                "air": [mail.new_message("air", "release", "", lane="lane/x", now=_T0),
                        mail.new_message("air", "note", "quiet", now=_T0)]}

    def _collect(self, board, monkeypatch, tmp_path, names=None, merged=None, **kw):
        _stub_channel(monkeypatch, board, self._channel(board), **kw)
        monkeypatch.setattr(board, "read_row_names", lambda root, base, **k: list(self._NAMES if names is None else names))
        run = _gh({"pr list": [], "pr list merged": self._LANES if merged is None else merged, "run list": _GREEN_RUNS})
        return board.collect(tmp_path, run_=run, now=_NOW), run

    def test_each_present_busy_or_shipping_seat_shows_its_lanes_since_its_newest_row(self, board, monkeypatch, tmp_path):
        """win and win-2 hold live claims; air-work holds nothing live but
        shipped a lane in the window, the end-of-day seat that owes its row;
        air is quiet with no checkout here and nothing merged, so it is not
        listed; lane/u no claim names is counted apart, never as some seat's
        zero. Dies to: a merge on the row's own day counted, a lane another
        seat released counted as this seat's, the shipping seat dropped, or the
        quiet seat listed."""
        lanes = self._LANES + [{"number": 5, "headRefName": "lane/u", "mergedAt": "2026-10-20T12:00:00Z"}]
        collected, _ = self._collect(board, monkeypatch, tmp_path, merged=lanes)
        assert collected["records"]["entries"] == [
            {"seat": "air-work", "merges": 1, "since": "", "parked": False, "where": "", "cut": False},
            {"seat": "win", "merges": 1, "since": "2026-10-18", "parked": False, "where": "base", "cut": False},
            {"seat": "win-2", "merges": 1, "since": "", "parked": False, "where": "", "cut": False}]
        assert collected["records"]["unclaimed"] == 1 and collected["records"]["read"] == 5
        text = board.render(collected)
        assert "records:  3 seats: air-work: 1 merge, no row on origin/main" in text, text
        assert "          win: 1 merge since its last row (2026-10-18)" in text, text
        assert "          win-2: 1 merge, no row on origin/main" in text, text
        assert "          and 1 of the last 5 merges no claim or seat label names" in text, text
        lines = text.splitlines()
        at = next(i for i, ln in enumerate(lines) if ln.startswith("records:"))
        assert lines[at - 1].startswith("          ") or lines[at - 1].startswith("seats:")
        assert lines[at + 4].startswith("jobs:"), "records: sits after seats: and before jobs:"

    def test_the_mail_line_says_when_the_records_refs_fetch_failed(self, board, monkeypatch, tmp_path):
        """The board fetched the mail and the base but never the records refs,
        so a dispatcher's days-long session read parked rows as of its start
        (failure-mode review). Dies to: the fetch dropped, or its failure read
        as fresh refs."""
        calls: list = []
        _stub_channel(monkeypatch, board, self._channel(board))
        monkeypatch.setattr(board, "read_row_names", lambda root, base, **k: list(self._NAMES))
        monkeypatch.setattr(board.mail, "fetch_records",
                            lambda root, run=None: calls.append(root) or (False, "could not reach origin"))
        collected = board.collect(tmp_path, run_=_gh({"pr list": [], "pr list merged": self._LANES,
                                                     "run list": _GREEN_RUNS}), now=_NOW)
        assert calls == [tmp_path]
        text = board.render(collected)
        assert ("mail:     the records refs' fetch failed (could not reach origin), so the parked rows are as last "
                "fetched") in text, text
        assert "records:  3 seats:" in text

    def test_an_unnamed_clone_says_so_and_a_json_answer_that_is_no_list_reads_as_unread(self, board, monkeypatch,
                                                                                        tmp_path):
        """An adopter's unnamed clone printed "no seat has a checkout here",
        which is false (failure-mode review); and a gh answer that is JSON but
        not a list went through prs() as no merges and printed 0, where the
        open-PR read refuses the same shape. Dies to: either read as a count."""
        _stub_channel(monkeypatch, board, self._channel(board))
        monkeypatch.setattr(board.mail, "machine_setting", lambda root, run=None: (None, "git config espalier.machine is not set"))
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS}), now=_NOW))
        assert "records:  none (this clone names no machine, so no seat's rows are read)" in text, text
        collected, _ = self._collect(board, monkeypatch, tmp_path, merged={"message": "rate limited"})
        text = board.render(collected)
        assert "records:  unread (gh pr list answered no list" in text, text
        counted = [ln for ln in text.splitlines() if ln.startswith("records:") and any(f"{n} merge" in ln for n in range(10))]
        assert not counted, text

    def test_a_row_parked_on_the_seats_records_ref_is_its_newest_and_the_line_says_so(self, board, monkeypatch, tmp_path):
        """The dispatcher's own 10-20 row sat parked on 10-23 while the base's
        newest was 10-19: the seat wrote its row and is not in debt, and the
        fold is owed. Dies to: the parked rows ignored, or the parked read's
        failure printed as a count."""
        seen: list = []

        def pending(root, directory, against, **kw):
            seen.append((directory, list(against)))
            assert kw.get("trailer") == board.FOLD_TRAILER, kw   # the pending rule's trailer rides the read (DEF-4045)
            return [("win", "memory/session-log.d/2026-10-19-210000-win.md", "refs/remotes/origin/records/win")]

        _stub_channel(monkeypatch, board, self._channel(board))
        monkeypatch.setattr(board, "read_row_names", lambda root, base, **k: list(self._NAMES))
        monkeypatch.setattr(board.mail, "pending", pending)
        run = _gh({"pr list": [], "pr list merged": self._LANES, "run list": _GREEN_RUNS})
        collected = board.collect(tmp_path, run_=run, now=_NOW)
        assert seen == [("memory/session-log.d", ["origin/main"])]
        win = next(e for e in collected["records"]["entries"] if e["seat"] == "win")
        assert win == {"seat": "win", "merges": 0, "since": "2026-10-19", "parked": True, "where": "parked", "cut": False}
        assert "win: 0 merges since its last row (2026-10-19, parked until the next fold)" in board.render(collected)
        monkeypatch.setattr(board.mail, "pending",
                            lambda *a, **k: (_ for _ in ()).throw(board.Unresolvable("git for-each-ref failed")))
        text = board.render(board.collect(tmp_path, run_=run, now=_NOW))
        assert "records:  unread (git for-each-ref failed)" in text, text

    def test_a_row_the_base_pruned_is_the_seats_newest_and_the_line_says_pruned(self, board, monkeypatch, tmp_path):
        """#354's prune (2026-10-30) took win's and win-2's newest rows off
        origin/main and this line read 'win: 24+ merges, no row on origin/main'
        for a seat that had rowed every lane -- the debt the ship driver's
        refusal would have stopped it on. The names the fold's prunes deleted
        are read from the base's history beside the tree, through the loader's
        one argv and parser; a deletion by a commit without the fold trailer
        is left out and counts as debt (the dispatcher's ruling, 2026-10-30).
        Dies to: the history read dropped, its failure read as no names, or a
        trailer-less deletion read as the seat's row."""
        seen: list = []
        names = ["memory/session-log.d/2026-10-19-053029-air.md"]
        pruned = ["memory/session-log.d/2026-10-15-073941-win.md", "memory/session-log.d/2026-10-18-165314-win.md"]
        collected, _ = self._collect(board, monkeypatch, tmp_path, names=names)
        monkeypatch.setattr(board, "read_pruned_names", lambda root, base, **k: seen.append((root, base)) or list(pruned))
        run = _gh({"pr list": [], "pr list merged": self._LANES, "run list": _GREEN_RUNS})
        collected = board.collect(tmp_path, run_=run, now=_NOW)
        assert seen == [(tmp_path, "main")]
        win = next(e for e in collected["records"]["entries"] if e["seat"] == "win")
        assert win == {"seat": "win", "merges": 1, "since": "2026-10-18", "parked": False, "where": "pruned", "cut": False}
        assert "win: 1 merge since its last row (2026-10-18, pruned from origin/main since)" in board.render(collected)
        monkeypatch.setattr(board, "read_pruned_names",
                            lambda *a, **k: (_ for _ in ()).throw(board.Unresolvable("git log origin/main failed")))
        text = board.render(board.collect(tmp_path, run_=run, now=_NOW))
        assert "records:  unread (git log origin/main failed)" in text, text
        # The real read asks whether the history is cut, then runs the loader's argv against origin/<base>
        # and keeps the prunes alone; a shallow clone is unread, never no pruned rows.
        calls: list = []

        def git(argv, **kw):
            calls.append(list(argv))
            if argv[1:] == board.SHALLOW_ARGV:
                return 0, "false\n", ""
            return 0, ("\x1e\x1f\nmemory/session-log.d/2026-10-21-120000-win.md\n"            # a revert: no trailer
                       "\x1esession-log\n\x1f\nmemory/session-log.d/2026-10-18-165314-win.md\n"), ""

        monkeypatch.undo()
        assert board.read_pruned_names(tmp_path, "main", run_=git) == ["memory/session-log.d/2026-10-18-165314-win.md"]
        assert calls == [["git", *board.SHALLOW_ARGV], ["git", *board.pruned_rows_argv("origin/main")]]
        failing = lambda argv, **kw: (128, "", "fatal: bad revision") if "log" in argv else (0, "false\n", "")  # noqa: E731
        with pytest.raises(board.Unresolvable, match="prunes deleted"):
            board.read_pruned_names(tmp_path, "main", run_=failing)
        shallow = lambda argv, **kw: (0, "true\n", "")  # noqa: E731
        with pytest.raises(board.Unresolvable, match="shallow clone"):
            board.read_pruned_names(tmp_path, "main", run_=shallow)

    def test_a_lane_no_claim_names_counts_for_the_seat_its_label_names(self, board, monkeypatch, tmp_path):
        """DEF-4044: a merged lane no claim names was nobody's (counted apart
        as 'no claim names'), so the row debt read it as zero and the cap was
        passed by not claiming; the seat:<name> label the ship driver stamps
        names it. Dies to: the label ignored, or read over a claim."""
        lanes = self._LANES + [
            {"number": 5, "headRefName": "lane/u", "mergedAt": "2026-10-20T12:00:00Z", "labels": [{"name": "seat:win"}]},
            {"number": 6, "headRefName": "lane/v", "mergedAt": "2026-10-20T12:00:00Z", "labels": [{"name": "seat:mac"}]},
            {"number": 7, "headRefName": "lane/w", "mergedAt": "2026-10-20T12:00:00Z"}]
        collected, _ = self._collect(board, monkeypatch, tmp_path, merged=lanes)
        entries = {e["seat"]: e for e in collected["records"]["entries"]}
        assert entries["win"]["merges"] == 2 and entries["mac"]["merges"] == 1   # mac: a seat only its label names
        assert collected["records"]["unclaimed"] == 1
        text = board.render(collected)
        assert "win: 2 merges since its last row (2026-10-18)" in text and "mac: 1 merge, no row on origin/main" in text
        assert "and 1 of the last 7 merges no claim or seat label names" in text

    def test_a_row_riding_an_open_pull_request_is_the_seats_newest_and_the_line_says_so(self, board, monkeypatch,
                                                                                         tmp_path):
        """A row on the seat's own open pull request is written and waits for
        its merge, neither on the base nor parked (the first lane's
        failure-mode review); the open pull requests' fetched heads are read
        after the open-PR section, and unread ones are said. Dies to: the
        riding names ignored, or the open pull requests' unread state silent."""
        seen: list = []
        _stub_channel(monkeypatch, board, self._channel(board))
        monkeypatch.setattr(board, "read_row_names", lambda root, base, **k: list(self._NAMES))
        monkeypatch.setattr(board, "read_riding_names",
                            lambda root, prs, seat_of, **k: seen.append([p.get("number") for p in prs])
                            or ["memory/session-log.d/2026-10-21-120000-win.md"])
        open_pr = {"number": 9, "headRefName": "lane/a", "headRefOid": "f" * 40, "mergeStateStatus": "CLEAN",
                   "isDraft": False, "autoMergeRequest": None, "title": "t", "files": []}
        run = _gh({"pr list": [open_pr], "pr list merged": self._LANES, "run list": _GREEN_RUNS})
        collected = board.collect(tmp_path, run_=run, now=_NOW, fetch=False)   # no head fetch: the runner answers gh alone
        assert seen == [[9]]
        win = next(e for e in collected["records"]["entries"] if e["seat"] == "win")
        assert win == {"seat": "win", "merges": 0, "since": "2026-10-21", "parked": False, "where": "open", "cut": False}
        assert "win: 0 merges since its last row (2026-10-21, riding its open pull request)" in board.render(collected)
        run = _gh({"pr list": board.Unresolvable("gh pr list answered no JSON"), "pr list merged": self._LANES,
                   "run list": _GREEN_RUNS})
        text = board.render(board.collect(tmp_path, run_=run, now=_NOW, fetch=False))
        assert "(the open pull requests are unread, so a row riding one is not counted)" in text, text
        # The real read: each head that is here, by object id, whose seat a claim or label names, and only
        # that seat's names on it: a head carries the base's fragments as of its branch point too (#348,
        # branched before the prune, carried win's pruned row and the live line said riding, 2026-10-30).
        calls: list = []

        def git(argv, **kw):
            calls.append(list(argv))
            if argv[1:3] == ["cat-file", "-e"]:
                return (0, "", "") if argv[3].startswith(("f" * 40, "e" * 40)) else (1, "", "")
            return 0, ("memory/session-log.d/2026-10-21-120000-win.md\n"
                       "memory/session-log.d/2026-10-18-165314-win-2.md\n"), ""

        monkeypatch.undo()
        prs = [open_pr, {"number": 10, "headRefOid": "0" * 40, "headRefName": "lane/a"},
               {"number": 11, "headRefOid": "f" * 40, "headRefName": "lane/a"},
               {"number": 348, "headRefOid": "e" * 40, "headRefName": "refresh-externals/x"}]   # nobody's: not read
        assert board.read_riding_names(tmp_path, prs, {"lane/a": "win"}, run_=git) == [
            "memory/session-log.d/2026-10-21-120000-win.md"]
        assert [c for c in calls if c[1] == "ls-tree"] == [
            ["git", "ls-tree", "--name-only", "f" * 40, "--", "memory/session-log.d/"]]
        assert board.riding_rows([("win-2", ["memory/session-log.d/2026-10-18-165314-win-2.md",
                                             "memory/session-log.d/2026-10-21-120000-win.md"]),
                                  ("", ["memory/session-log.d/2026-10-21-120000-air.md"])]) == [
            "memory/session-log.d/2026-10-18-165314-win-2.md"]

    def test_the_read_is_the_base_tree_through_the_lane_fields_in_the_shared_window(self, board, monkeypatch, tmp_path):
        """Dies to: the names read from the working tree, the rollup fields
        asked for a hundred rows, or a window of the board's own."""
        seen: list[tuple] = []
        _stub_channel(monkeypatch, board, self._channel(board))
        monkeypatch.setattr(board, "read_row_names", lambda root, base, **k: seen.append((root, base)) or list(self._NAMES))
        run = _gh({"pr list": [], "pr list merged": self._LANES, "run list": _GREEN_RUNS})
        collected = board.collect(tmp_path, run_=run, now=_NOW)
        assert seen == [(tmp_path, "main")]
        reads = [c for c in run.calls if c[:3] == ["gh", "pr", "list"] and "merged" in c
                 and "headRefName" in c[c.index("--json") + 1]]
        assert len(reads) == 1 and reads[0][reads[0].index("--limit") + 1] == str(board.ROW_DEBT_WINDOW)
        assert collected["records"]["window"] == board.ROW_DEBT_WINDOW >= 75

    def test_no_present_or_busy_seat_reads_as_none_and_reads_nothing(self, board, monkeypatch, tmp_path):
        mail = board.mail
        quiet = {"air": [mail.new_message("air", "note", "quiet", now=_T0)]}
        _stub_channel(monkeypatch, board, quiet)
        monkeypatch.setattr(board, "read_row_names", lambda *a, **k: (_ for _ in ()).throw(AssertionError("read")))
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS}), now=_NOW))
        assert "records:  none (no seat has a checkout here, a live claim, a job or a lane merged in the window)" in text, text

    def test_an_unreadable_tree_or_merged_list_reads_as_unread_never_as_zero(self, board, monkeypatch, tmp_path):
        """Dies to: a failed read printed as 0 merges, which reads as a clean seat."""
        collected, _ = self._collect(board, monkeypatch, tmp_path,
                                     merged=board.Unresolvable("gh pr list answered rc=4 with no JSON: not logged in"))
        text = board.render(collected)
        assert "records:  unread (gh pr list answered rc=4 with no JSON: not logged in)" in text, text
        assert "0 merges" not in text
        _stub_channel(monkeypatch, board, self._channel(board))
        monkeypatch.setattr(board, "read_row_names",
                            lambda *a, **k: (_ for _ in ()).throw(board.Unresolvable("git ls-tree origin/main failed")))
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "pr list merged": self._LANES,
                                                              "run list": _GREEN_RUNS}), now=_NOW))
        assert "records:  unread (git ls-tree origin/main failed)" in text, text
        assert "post-merge proof green" in text, "one unreadable section costs only itself"

    def test_unread_mail_reads_as_unread(self, board, monkeypatch, tmp_path):
        collected, _ = self._collect(board, monkeypatch, tmp_path, read_error="git for-each-ref failed")
        assert "records:  unread (the mail could not be read: git for-each-ref failed)" in board.render(collected)

    def test_a_count_is_a_floor_when_the_read_stops_short_of_the_seats_newest_row(self, board, monkeypatch, tmp_path):
        """The window is the last 100 merges across EVERY seat, so one seat
        can reach 100 only if every merge read is its own; the first cut rule
        compared a seat's count with the window and never fired (code review).
        A count is a floor when the read is full and its oldest merge is still
        newer than the seat's row (or the seat has none). Dies to: the flag
        read from the count, or a seat with a row newer than the oldest merge
        read marked as cut."""
        w = board.ROW_DEBT_WINDOW
        many = ([{"number": n, "headRefName": "lane/a", "mergedAt": "2026-10-20T12:00:00Z"} for n in range(60)]
                + [{"number": 100 + n, "headRefName": "lane/d", "mergedAt": "2026-10-19T12:00:00Z"} for n in range(w - 60)])
        names = ["memory/session-log.d/2026-10-10-073941-win.md", "memory/session-log.d/2026-10-20-053029-win-2.md"]
        collected, _ = self._collect(board, monkeypatch, tmp_path, names=names, merged=many)
        text = board.render(collected)
        assert f"air-work: {w - 60}+ merges, no row on origin/main (the last {w} read)" in text, text
        assert f"win: 60+ merges since its last row (2026-10-10; the last {w} read)" in text, text
        assert "win-2: 0 merges since its last row (2026-10-20)" in text, text
        assert [e["cut"] for e in collected["records"]["entries"]] == [True, True, False]
        # Short of the window, nothing is a floor however many lanes a seat has.
        collected, _ = self._collect(board, monkeypatch, tmp_path, names=names, merged=many[:w - 1])
        assert not any(e["cut"] for e in collected["records"]["entries"])
        assert "+ merges" not in board.render(collected)

    def test_the_row_names_are_git_ls_tree_of_the_base_and_a_failure_is_named(self, board, tmp_path):
        """Dies to: a working-tree listing, or a failed git read as no rows."""
        calls: list[list[str]] = []

        def run(argv, **kw):
            calls.append(list(argv))
            return (0, "memory/session-log.d/2026-10-18-163553-win.md\nmemory/session-log.d/x.md\n", "")

        assert board.read_row_names(tmp_path, "main", run_=run) == ["memory/session-log.d/2026-10-18-163553-win.md",
                                                                     "memory/session-log.d/x.md"]
        assert calls == [["git", "ls-tree", "--name-only", "origin/main", "--", "memory/session-log.d/"]]
        with pytest.raises(board.Unresolvable, match="ls-tree"):
            board.read_row_names(tmp_path, "main", run_=lambda argv, **kw: (128, "", "fatal: not a tree"))


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


def _git_for(main: Path, *worktrees: Path, clone: str | None = "air", names: dict | None = None,
             shared: dict | None = None, listing: str | None = None):
    """A runner answering the git reads the seats line makes: this clone's
    checkouts (``worktree list --porcelain``, or ``listing``), the clone's
    machine name, the name each checkout answers (``config --get
    espalier.machine`` with it as cwd; by default the clone's for the main
    checkout and ``<clone>-<directory>``, SessionStart's naming, for a
    worktree), and what ``mail.naming_steps`` reads there: ``shared`` gives
    the clone's core.bare / core.worktree (unset by default) and
    ``--git-common-dir`` (``<main>/.git`` by default)."""
    if names is None:
        names = {str(main): clone, **{str(w): f"{clone}-{w.name}" for w in worktrees}} if clone else {}
    shared = {"--git-common-dir": str(main / ".git"), **(shared or {})}

    def run(argv, **kw):
        if argv[1:3] == ["worktree", "list"]:
            if listing is not None:
                return 0, listing, ""
            blocks = [f"worktree {main}\nHEAD {'1' * 40}\nbranch refs/heads/main\n"]
            blocks += [f"worktree {w}\nHEAD {'2' * 40}\nbranch refs/heads/lane/{w.name}\n" for w in worktrees]
            return 0, "\n".join(blocks), ""
        if argv[1:3] == ["config", "--local"]:
            return (0, clone + "\n", "") if clone else (1, "", "")
        if argv[1:] in (["rev-parse", "--git-common-dir"], ["config", "--get", "core.bare"],
                        ["config", "--get", "core.worktree"]):
            value = shared.get(argv[-1])
            return (0, value + "\n", "") if value else (1, "", "")
        if argv[1:3] == ["config", "--get"]:
            cwd = str(kw.get("cwd"))
            if not Path(cwd).is_dir():
                return 128, "", f"fatal: cannot change to '{cwd}': No such file or directory"   # as git does
            name = names.get(cwd)
            if isinstance(name, Exception):
                raise name
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
        text = self._text(board, first_only)
        assert "air-x: no mail; 1 live session in .claude/worktrees/work" in text, text
        assert "work2" not in text, "a second holder of a name gets a row only while it holds a session"

    def test_a_worktree_answering_the_clones_name_is_flagged_with_its_remedy(self, board, tmp_path):
        """The inherited-name state (docs/SHARP_EDGES.md, "The worktrees of one
        clone share its machine name") is flagged even when the main checkout
        has no row of its own, and the row says how to name it; the JSON keeps
        the bare name beside the row's key (both reviewers, r2). Dies to: the
        flag read only from a first row that happens to be shown."""
        main, work = self._clone(tmp_path)
        rows, _ = self._seats(board, main, work, _registry(tmp_path, work), names={str(main): "air", str(work): "air"})
        [row] = rows
        assert row["seat"] == "air [.claude/worktrees/work]" and row["name"] == "air"
        text = self._text(board, rows)
        assert ("air [.claude/worktrees/work]: the seat name of the main checkout too (one mail ref for both); "
                f'1 live session in .claude/worktrees/work; name it: git -C "{work}" config extensions.worktreeConfig '
                f'true && git -C "{work}" config --worktree espalier.machine <name>') in text, text

    def test_a_bare_clones_worktree_gets_the_core_bare_step_not_the_commands(self, board, tmp_path):
        """Naming a bare clone's worktree takes one change, core.bare moved
        into the main worktree's config.worktree (the bare repository's own,
        whose path the listing gives), then a fresh session in that worktree
        names it (dispatcher, f43314 (i')); no commands, and the worktree by
        its path, since the board is read in another checkout (code review
        r7). Dies to: a command, a second change, or "this worktree"."""
        main, work = self._clone(tmp_path)
        run = _git_for(main, work, names={str(work): "air"}, shared={"core.bare": "true", "--git-common-dir": str(main)},
                       listing=f"worktree {main}\nbare\n\nworktree {work}\nHEAD {'2' * 40}\nbranch refs/heads/x\n")
        local = board.read_sessions(main, run_=run, config_dir=_registry(tmp_path, work), inside_session=False)
        text = self._text(board, board.seat_rows({}, local, _NOW))
        assert "air [" in text and "core.bare" in text, text
        assert f"main worktree's config.worktree ({main.resolve() / 'config.worktree'})" in text, text
        assert f"a fresh session in {work}" in text and "this worktree" not in text, text
        assert "extensions.worktreeConfig" not in text and "git config" not in text and "git -C" not in text, text

    def test_a_core_worktree_clone_gets_the_one_change_though_its_listing_is_not_bare(self, board, tmp_path):
        """A clone whose shared config sets core.worktree lists no bare entry,
        and the pair pasted there points the worktree at the main checkout's
        files (failure-mode review r9, measured on git 2.39.5); the one owner,
        mail.naming_steps, reads both keys. Dies to: the board deciding from
        the listing's bare line."""
        main, work = self._clone(tmp_path)
        run = _git_for(main, work, names={str(main): "air", str(work): "air"}, shared={"core.worktree": str(main)})
        local = board.read_sessions(main, run_=run, config_dir=_registry(tmp_path, work), inside_session=False)
        text = self._text(board, board.seat_rows({}, local, _NOW))
        assert "air [.claude/worktrees/work]" in text and "sets core.worktree" in text, text
        assert f"a fresh session in {work}" in text, text
        assert "extensions.worktreeConfig" not in text and "git -C" not in text, text

    def test_the_config_worktree_path_is_gits_common_dir_not_the_listings(self, board, tmp_path):
        """A bare repository whose directory is named .git is listed as its
        parent, whose config.worktree git never reads (code review r9); the
        path is --git-common-dir's, read in the worktree, as the banner's is.
        Dies to: the path taken from the listing."""
        main, work = self._clone(tmp_path)
        common = main / ".git"
        run = _git_for(main, work, names={str(work): "air"}, shared={"core.bare": "true", "--git-common-dir": str(common)},
                       listing=f"worktree {main}\nbare\n\nworktree {work}\nHEAD {'2' * 40}\nbranch refs/heads/x\n")
        local = board.read_sessions(main, run_=run, config_dir=_registry(tmp_path, work), inside_session=False)
        text = self._text(board, board.seat_rows({}, local, _NOW))
        assert f"({common.resolve() / 'config.worktree'})" in text, text
        assert f"({main.resolve() / 'config.worktree'})" not in text, text

    def test_the_flag_reads_the_clones_name_not_the_main_checkouts(self, board, tmp_path):
        """The board runs in the main checkout, and a naming command pasted
        there without `git -C` renames the MAIN checkout; the worktree still
        answering the clone's name must stay flagged then, and the main
        checkout answering another name is said (failure-mode review, r3 case
        C and r4). Dies to: the flag compared against the main checkout's
        answer, or the renamed main checkout left unsaid."""
        main, work = self._clone(tmp_path)
        rows, _ = self._seats(board, main, work, _registry(tmp_path, main, work),
                              names={str(main): "air-main", str(work): "air"})
        text = self._text(board, rows)
        assert "air [.claude/worktrees/work]: the seat name of the clone too (one mail ref for both)" in text, text
        assert ("air-main: no mail; 1 live session in the main checkout; it answers air-main, not its clone's "
                "name air (a --worktree name was set here)") in text, text

    def test_the_flag_also_reads_the_main_checkouts_name(self, board, tmp_path):
        """Dies to: the flag compared against the clone's name alone."""
        main, work = self._clone(tmp_path)
        rows, _ = self._seats(board, main, work, _registry(tmp_path, work),
                              names={str(main): "air-x", str(work): "air-x"})
        assert "air-x [.claude/worktrees/work]: the seat name of the main checkout too" in self._text(board, rows)

    def test_a_name_read_that_failed_is_unread_and_folds_nothing(self, board, tmp_path):
        """A timeout is not "no name": the real seat's row would fold into "no
        live session here" while it holds one, so nothing folds and the board
        says why, also when the checkout holds no session (both reviewers, r3
        and r4). Dies to: the failed read rendered as no seat name, or the
        reason dropped."""
        main, work = self._clone(tmp_path)
        old = board.mail.new_message("air-work", "note", "x", now=datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc))
        timeout = board.Unresolvable("git config took longer than 10s")
        for registry in (_registry(tmp_path, work), _registry(tmp_path / "idle")):
            rows, local = self._seats(board, main, work, registry, {"air-work": [old]},
                                      names={str(main): "air", str(work): timeout})
            text = self._text(board, rows, names_unread=board.unread_names(local))
            assert "air-work: last mail 14 d 2 h ago (note)" in text and "no mail in 7 d" not in text, text
            assert (f"nothing folds: the seat name of {work} is unread (git config could not be read "
                    "(git config took longer than 10s)") in text, text
        rows, local = self._seats(board, main, work, _registry(tmp_path / "busy", work), None,
                                  names={str(main): "air", str(work): timeout})
        text = self._text(board, rows, names_unread=board.unread_names(local))
        assert f"(seat name unread) {work}: mail unknown; 1 live session in .claude/worktrees/work" in text, text

    def test_a_clone_name_read_that_failed_reads_the_local_sessions_as_unread(self, board, tmp_path):
        """Without the clone's own name a worktree still answering it cannot be
        told from one named by hand, and a gone folder's seat cannot be
        derived. Dies to the failed read taken for a clone that names no
        machine (clone_machine's None), which folded the local seats on it."""
        main, work = self._clone(tmp_path)
        base = _git_for(main, work)
        failures = (board.Unresolvable("git config took longer than 10s"),
                    (128, "", "fatal: bad config line 3 in file .git/config"))
        for i, failed in enumerate(failures):
            def run(argv, _failed=failed, **kw):
                if argv[1:3] == ["config", "--local"]:
                    if isinstance(_failed, Exception):
                        raise _failed
                    return _failed
                return base(argv, **kw)
            local = board.read_sessions(main, run_=run, config_dir=_registry(tmp_path / str(i), work),
                                        inside_session=False)
            assert local["checkouts"] == [], local
            assert "clone's own machine name could not be read" in local["unread"], local
            assert board.mail.MACHINE_UNREAD in local["unread"], local

    def test_a_checkout_answering_no_usable_name_is_not_given_one(self, board, tmp_path):
        """A hand-set name the channel refuses (`Air-2`) turns the channel off
        there; the derived name is not one that checkout answers (failure-mode
        review, r2). Dies to: the derived name as a fallback for a folder that
        is there."""
        main, work = self._clone(tmp_path)
        rows, _ = self._seats(board, main, work, _registry(tmp_path, work), names={str(main): "air"})
        text = self._text(board, rows)
        assert f"(no seat name) {work}: no mail; 1 live session in .claude/worktrees/work" in text, text
        assert "air-work" not in text

    def test_a_session_in_a_worktree_whose_folder_is_gone_stays_with_it(self, board, tmp_path):
        """A worktree's folder removed under a running session (Assumption 6's
        2026-10-08 cleanup): git still lists it, and its session belongs to
        it, not to the main checkout above it, which then read as TWO
        SESSIONS (code review, r2: a regression of the r1 fold). Dies to: the
        listed checkout skipped because its folder is gone."""
        main = tmp_path / "repo"
        main.mkdir()
        gone = main / ".claude" / "worktrees" / "gone"
        rows, _ = self._seats(board, main, gone, _registry(tmp_path, main, gone))
        text = self._text(board, rows)
        assert ("air-gone: no mail; 1 live session in .claude/worktrees/gone (its folder is gone, so its seat name "
                "is the derived one)") in text, text
        assert "TWO SESSIONS" not in text
        text = self._text(board, board.seat_rows({}, board.read_sessions(
            main, run_=_git_for(main, gone, clone=None), config_dir=_registry(tmp_path / "v", gone),
            inside_session=False), _NOW))
        assert f"(no seat name) {gone}: no mail; 1 live session in .claude/worktrees/gone (its folder is gone)" in text
        assert "derived" not in text, "a row with no name says nothing of a derived one (r4)"

    def test_a_bare_main_entry_is_no_checkout(self, board, tmp_path):
        main, work = self._clone(tmp_path)
        run = _git_for(main, work, names={str(work): "air-work"},
                       listing=f"worktree {main}\nbare\n\nworktree {work}\nHEAD {'2' * 40}\nbranch refs/heads/x\n")
        local = board.read_sessions(main, run_=run, config_dir=_registry(tmp_path, work), inside_session=False)
        assert [c["path"] for c in local["checkouts"]] == [str(work)]

    def test_the_unchecked_row_names_every_registry_read(self, board, tmp_path, monkeypatch):
        """With CLAUDE_CONFIG_DIR set, the registry read is that directory and
        the home one; the row named only the first (code review, r2)."""
        import importlib

        main, work = self._clone(tmp_path)
        board.read_sessions(main, run_=_git_for(main, work), config_dir=_registry(tmp_path, work), inside_session=False)
        sync = importlib.import_module("checkout_sync")
        monkeypatch.setattr(sync, "claude_config_dirs", lambda: [tmp_path / "cfg", tmp_path / "home"])
        monkeypatch.setattr(sync, "live_sessions", lambda config_dir=None: [])
        local = board.read_sessions(main, run_=_git_for(main, work), inside_session=False)
        assert str(tmp_path / "cfg" / "sessions") in local["registry"]
        assert str(tmp_path / "home" / "sessions") in local["registry"]

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

    def test_the_fold_never_hides_a_live_session_a_claim_or_a_job(self, board, monkeypatch, tmp_path):
        """A seat with a live session, or one a live claim or job names, is
        shown whatever its last mail's age (both reviewers, r2). Dies to: the
        fold judged on the mail's age alone."""
        old = 10 * 86400
        live = {"seat": "air-old", "last_mail": {"type": "note", "age_s": old}, "checkout": "wt/a", "shared": False,
                "sessions": [{"pid": 1, "session_id": "abc"}]}
        assert "air-old: last mail 10 d 0 h ago (note); 1 live session in wt/a" in self._text(board, [live])
        t = datetime(2026, 10, 5, 0, 0, 0, tzinfo=timezone.utc)
        claim = board.mail.new_message("win-3", "claim", "", lane="lane/held", now=t)
        note = board.mail.new_message("win-4", "note", "x", now=t)
        job = board.mail.new_message("air", "assign", "", seat="win-4", lane="lane/job", now=_T0)
        fresh = board.mail.new_message("win-5", "claim", "", lane="lane/fresh", now=_T0)
        _stub_channel(monkeypatch, board, {"win-3": [claim], "win-4": [note], "air": [job], "win-5": [fresh]})
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS}), now=_NOW))
        assert "win-3: last mail 10 d 2 h ago (claim); kept: it holds a live claim (only win-3 can release it)" in text
        assert "win-4: last mail 10 d 2 h ago (note); kept: a live job names it" in text, text
        row = next(ln for ln in text.splitlines() if "win-5:" in ln)
        assert row.endswith("win-5: last mail 6 h 25 min ago (claim)"), "kept: is said only past the fold's age"

    def test_nothing_folds_while_the_registry_is_unread(self, board):
        """The fold says "no live session here", which an unread registry
        cannot support (both reviewers, r2). Dies to: the fold run anyway."""
        row = {"seat": "air-old", "last_mail": {"type": "note", "age_s": 10 * 86400}, "sessions": None}
        text = board.render({"seats": {"rows": [row], "unread": "the registry could not be read in full"}})
        assert "air-old: last mail" in text and "no live session here" not in text, text

    def test_other_seats_unread_sits_beside_the_local_rows(self, board, monkeypatch, tmp_path):
        """Dies to: the unread-mail row printed only when no local row is."""
        local = {"checkouts": [{"path": str(tmp_path), "main": True, "seat": "win",
                                "sessions": [{"pid": 7, "session_id": "abcdef0123"}]}], "unread": "", "checked": True}
        _stub_channel(monkeypatch, board, read_error="git for-each-ref failed", sessions=local)
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS}), now=_NOW))
        assert "seats:    1 seat: win: mail unread; 1 live session in the main checkout" in text, text
        assert "          other seats unread (the mail could not be read: git for-each-ref failed)" in text, text

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
        assert "seats:    1 seat: win: last mail 6 h 25 min ago (note); 1 live session in the main checkout" in text, text
        _stub_channel(monkeypatch, board, {"win": [note]}, sessions={"checkouts": [], "unread": "registry gone"})
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS}), now=_NOW))
        assert "          live sessions here unread: registry gone" in text, text

    def test_collect_carries_an_idle_checkouts_unread_name(self, board, monkeypatch, tmp_path):
        """A checkout holding no session gets no row, so only collect's
        names_unread can stop the fold for it (code review r5, M1). Dies to:
        collect dropping the list."""
        old = board.mail.new_message("air-old", "note", "x", now=datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc))
        local = {"checkouts": [{"path": "/r/wt", "main": False, "seat": "", "sessions": [],
                                "name_unread": "git config could not be read (took longer than 10s)"}],
                 "unread": "", "checked": True}
        _stub_channel(monkeypatch, board, {"air-old": [old]}, sessions=local)
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS}), now=_NOW))
        assert "air-old: last mail 14 d 2 h ago (note)" in text and "nothing folds: the seat name of /r/wt" in text

    def test_an_unread_machine_name_is_not_called_unnamed(self, board, monkeypatch, tmp_path):
        """Dies to: the mail note saying the clone names no machine when the
        name read failed (failure-mode review, r5)."""
        _stub_channel(monkeypatch, board)
        monkeypatch.setattr(board.mail, "machine_setting",
                            lambda root, run=None: (None, f"{board.mail.MACHINE_UNREAD} (took longer than 10s)"))
        text = board.render(board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS}), now=_NOW))
        assert "mail:     this checkout's machine name could not be read" in text, text
        assert "names no machine" not in text

    def test_the_main_checkouts_note_needs_a_name_other_than_the_clones(self, board, tmp_path):
        """Dies to: either guard on the note (code review r5, M6/M7/M14)."""
        main, work = self._clone(tmp_path)
        note = board.mail.new_message("air-main", "note", "x", now=_T0)
        rows, _ = self._seats(board, main, work, _registry(tmp_path), {"air-main": [note]},
                              names={str(main): "air-main", str(work): "air-work"})
        assert ("air-main: last mail 6 h 25 min ago (note); no live session in the main checkout; it answers "
                "air-main, not its clone's name air") in self._text(board, rows)
        plain, _ = self._seats(board, main, work, _registry(tmp_path / "p", main))
        assert "it answers" not in self._text(board, plain)

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
        assert "seats:    1 seat: air-work: no mail; 2 live sessions in .claude/worktrees/work (pid " in text, text
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
        assert {"asks", "seats", "open_prs", "post_merge", "post_merge_checks", "assignments", "claims"} <= set(collected)
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
            copy_checkout(REPO_ROOT / "task-packs" / "ledger.d", packs / "ledger.d")
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


#: The placement rule a current claim is stamped with: the mapper's own
#: ``_symbols.RULE``, a digest of its source, read here for the rows built at
#: collection; pinned equal to the board's below.
_RULE = _load("_symbols", "_symbols_rule_for_board_rows").RULE


def _claim(seat: str, lane: str, paths, symbols=(), ids=(), more: int = 0, rule: object = _RULE) -> dict:
    """One live claim as ``mail.live_claims`` returns it, symbols under the
    optional key the derivation writes, stamped with the rule that derived
    them (``rule=None``: a claim from before the stamp)."""
    re_ = {"lane": lane, "classes": [], "paths": list(paths), "ids": list(ids)}
    if symbols:
        re_["symbols"] = list(symbols)
        if rule is not None:
            re_["symbols_rule"] = rule
    if more:
        re_["symbols_more"] = more
    return {"id": f"c-{seat}-{lane}", "from": seat, "type": "claim", "at": "2026-10-17T09:00:00Z", "re": re_}


def _pr(number: int, seat: str, lane: str, head: str, paths=("a.py",)) -> dict:
    return {"number": number, "headRefName": lane, "headRefOid": head, "seat": seat,
            "files": [{"path": p} for p in paths]}


def _placed(path: str, *names: str, unplaced: int = 0) -> dict:
    """``{path: placement}`` as ``_symbols.symbols_between`` returns it."""
    return {path: {"kind": "python" if path.endswith(".py") else "path",
                   "symbols": {f"{path}::{n}" for n in names} if path.endswith(".py") else {path},
                   "changed": max(1, len(names)) if path.endswith(".py") else 0, "unplaced": unplaced}}


def _heads(present: set, fetchable: frozenset = frozenset(), fetch_error: str = ""):
    """A git runner for the overlaps read: ``cat-file -e`` answers from
    ``present``; ``fetch`` lands the ``fetchable`` heads it names (or fails
    with ``fetch_error``); ``merge-base`` answers one base."""
    calls: list[list[str]] = []

    def run(argv, **kw):
        calls.append([*argv, f"timeout={kw.get('timeout')}"])
        if argv[:3] == ["git", "cat-file", "-e"]:
            return (0, "", "") if argv[3].split("^", 1)[0] in present else (1, "", "fatal: not a valid object")
        if argv[:3] == ["git", "fetch", "origin"]:
            if fetch_error:
                return 128, "", fetch_error
            present.update(oid for oid in argv[3:] if oid in fetchable)
            return 0, "", ""
        if argv[:2] == ["git", "merge-base"]:
            return 0, "b" * 40 + "\n", ""
        raise AssertionError(f"unexpected call {argv}")

    run.calls = calls  # type: ignore[attr-defined]
    return run


H1, H2, H3 = "1" * 40, "2" * 40, "3" * 40


class TestOverlapsSection:
    """TP-702 Wave 2 (2-A, 2-D): the board's ``overlaps:`` section, one line
    per pair among the live claims of different seats and the open pull
    requests, in the words the pack writes. The symbol reads are stubbed by
    head; the mapper itself is pinned in tests/test_symbols.py."""

    @pytest.fixture
    def by_head(self, board, monkeypatch):
        table: dict[str, dict] = {}

        def between(base, head, **kw):
            if isinstance(table.get(head), Exception):
                raise table[head]
            return table[head]

        monkeypatch.setattr(board._symbols, "symbols_between", between)
        return table

    def test_two_claims_sharing_a_symbol_print_one_line(self, board, tmp_path, by_head):
        """Dies to: the pair rule bypassed (two lanes in one function read as a
        path hit)."""
        claims = [_claim("win", "lane/x", ["a.py"], ["a.py::f"], ["DEF-1"]),
                  _claim("air-work", "lane/y", ["a.py"], ["a.py::f", "a.py::g"])]
        got = board.read_overlaps_section(tmp_path, "main", claims, [], run_=_heads(set()))
        assert board.overlap_lines(got) == [
            "overlaps: 1 pair: win (lane/x, DEF-1) and air-work (lane/y) meet at a.py::f"]

    def test_the_same_file_in_different_functions_prints_the_certificate(self, board, tmp_path, by_head):
        """Dies to: the certificate inverted (two lanes in different functions
        read as meeting, or one function as different ones)."""
        claims = [_claim("win", "lane/x", ["a.py"], ["a.py::f"]),
                  _claim("air-work", "lane/y", ["a.py"], ["a.py::g"])]
        got = board.read_overlaps_section(tmp_path, "main", claims, [], run_=_heads(set()))
        assert board.overlap_lines(got) == [
            "overlaps: 1 pair: win (lane/x) and air-work (lane/y) both changed a.py: different functions, "
            "none shared or next to the other's"]
        # Every pair carries the sides it declines on, none here: the --json shape never drops a key.
        assert got["pairs"][0]["unplaced_labels"] == [] and got["pairs"][0]["unplaced_on"] == []

    @pytest.mark.parametrize("other", [
        _claim("air-work", "lane/y", ["a.py"]),                                   # the file claimed whole
        _claim("air-work", "lane/y", ["a.py"], ["a.py::g", "a.py::<module>"]),     # a line no node holds
        _claim("air-work", "lane/y", ["a.py"], ["a.py::g"], more=3),               # a list the cap cut
    ], ids=["whole", "module-mark", "cut-list"])
    def test_a_side_with_unplaced_lines_prints_unplaced_never_the_certificate(self, board, tmp_path, by_head, other):
        """Dies to: an incomplete side certified (a claim whose list does not
        name every changed line reads as different functions)."""
        claims = [_claim("win", "lane/x", ["a.py"], ["a.py::f"]), other]
        lines = board.overlap_lines(board.read_overlaps_section(tmp_path, "main", claims, [], run_=_heads(set())))
        assert lines == ["overlaps: 1 pair: win (lane/x) and air-work (lane/y) both changed a.py: "
                         "unplaced lines on air-work's side"], lines

    def test_an_open_pull_requests_symbols_come_from_its_head_not_its_claim(self, board, tmp_path, by_head):
        """Dies to: the pull request's symbols read from its claim (the claim
        names f; the head changed g, which the other seat claims)."""
        by_head[H1] = _placed("a.py", "g")
        claims = [_claim("win", "lane/x", ["a.py"], ["a.py::f"]),
                  _claim("air-work", "lane/y", ["a.py"], ["a.py::g"])]
        got = board.read_overlaps_section(tmp_path, "main", claims, [_pr(7, "win", "lane/x", H1)],
                                          run_=_heads({H1}))
        assert board.overlap_lines(got) == ["overlaps: 1 pair: air-work (lane/y) and #7 win (lane/x) meet at a.py::g"]

    def test_a_head_not_here_prints_the_not_read_state(self, board, tmp_path, by_head):
        """Dies to: an unread head given a function verdict (its paths are
        GitHub's list, its symbols unknown)."""
        claims = [_claim("air-work", "lane/y", ["a.py"], ["a.py::g"])]
        got = board.read_overlaps_section(tmp_path, "main", claims, [_pr(7, "win", "lane/x", H1)],
                                          run_=_heads(set()))
        lines = board.overlap_lines(got)
        assert lines[0] == ("overlaps: 1 pair among what was read: air-work (lane/y) and #7 win (lane/x) "
                            "both changed a.py (symbols not read for #7: head not here)"), lines
        assert not any("different functions" in ln or " meet at " in ln for ln in lines)

    def test_two_pull_requests_with_no_claim_between_them_are_compared(self, board, tmp_path, by_head):
        """Dies to: pull requests read only against claims."""
        by_head.update({H1: _placed("a.py", "f"), H2: _placed("a.py", "f")})
        prs = [_pr(7, "win", "lane/x", H1), _pr(8, "air-work", "lane/y", H2)]
        got = board.read_overlaps_section(tmp_path, "main", [], prs, run_=_heads({H1, H2}))
        assert board.overlap_lines(got) == ["overlaps: 1 pair: #7 win (lane/x) and #8 air-work (lane/y) meet at a.py::f"]

    def test_a_seat_never_meets_itself(self, board, tmp_path, by_head):
        """Dies to: the same-seat skip removed (a seat's two lanes, or its claim
        and its pull request, read as an overlap it must answer)."""
        by_head[H1] = _placed("a.py", "f")
        claims = [_claim("win", "lane/x", ["a.py"], ["a.py::f"]), _claim("win", "lane/z", ["a.py"], ["a.py::f"])]
        got = board.read_overlaps_section(tmp_path, "main", claims, [_pr(7, "win", "lane/q", H1)],
                                          run_=_heads({H1}))
        assert board.overlap_lines(got) == ["overlaps: none"]

    def test_the_vendored_twin_meets_its_source(self, board, tmp_path, by_head):
        """Dies to: the twin left unfolded (a lane that edits the mirror reads
        as touching another file)."""
        claims = [_claim("win", "lane/x", ["espalier/_vendor/cc/x.py"], ["espalier/_vendor/cc/x.py::k"]),
                  _claim("air-work", "lane/y", ["tools/cc/x.py"], ["tools/cc/x.py::k"])]
        got = board.read_overlaps_section(tmp_path, "main", claims, [], run_=_heads(set()))
        assert board.overlap_lines(got) == [
            "overlaps: 1 pair: win (lane/x) and air-work (lane/y) meet at tools/cc/x.py::k"]

    def test_prose_is_a_path_tier(self, board, tmp_path, by_head):
        claims = [_claim("win", "lane/x", ["docs/a.md"]), _claim("air-work", "lane/y", ["docs/a.md"])]
        got = board.read_overlaps_section(tmp_path, "main", claims, [], run_=_heads(set()))
        assert board.overlap_lines(got) == [
            "overlaps: 1 pair: win (lane/x) and air-work (lane/y) both changed docs/a.md "
            "(no symbols: not Python, or a folder claimed whole)"]

    def test_a_directory_claim_covers_the_files_under_it(self, board, tmp_path, by_head):
        """Dies to: a folded directory claim matched by its spelling alone (a
        claim past the path cap would meet nothing)."""
        claims = [_claim("win", "lane/x", ["tools/cc"]), _claim("air-work", "lane/y", ["tools/cc/x.py"],
                                                                ["tools/cc/x.py::k"])]
        got = board.read_overlaps_section(tmp_path, "main", claims, [], run_=_heads(set()))
        assert board.overlap_lines(got) == [
            "overlaps: 1 pair: win (lane/x) and air-work (lane/y) both changed tools/cc/x.py: unplaced lines on win's side"]

    def test_the_missing_heads_are_fetched_in_one_bounded_call(self, board, tmp_path, by_head):
        """Dies to: a fetch per head, an unbounded one, or one for a head
        already here."""
        by_head.update({H1: _placed("a.py", "f"), H2: _placed("a.py", "g"), H3: _placed("a.py", "h")})
        prs = [_pr(7, "win", "lane/x", H1), _pr(8, "air-work", "lane/y", H2), _pr(9, "air", "lane/z", H3)]
        run_ = _heads({H1}, fetchable=frozenset({H2, H3}))
        board.read_overlaps_section(tmp_path, "main", [], prs, run_=run_)
        fetches = [c for c in run_.calls if c[1] == "fetch"]
        assert len(fetches) == 1 and fetches[0][3:-1] == [H2, H3], fetches
        assert fetches[0][-1] == f"timeout={board.OVERLAP_FETCH_TIMEOUT}"
        run_ = _heads({H1, H2, H3})
        board.read_overlaps_section(tmp_path, "main", [], prs, run_=run_)
        assert not [c for c in run_.calls if c[1] == "fetch"]

    def test_a_failed_fetch_reads_those_heads_as_not_read_and_says_why(self, board, tmp_path, by_head):
        claims = [_claim("air-work", "lane/y", ["a.py"], ["a.py::g"])]
        run_ = _heads(set(), fetch_error="fatal: unable to access origin")
        got = board.read_overlaps_section(tmp_path, "main", claims, [_pr(7, "win", "lane/x", H1)], run_=run_)
        lines = board.overlap_lines(got)
        assert "symbols not read for #7: head not here" in lines[0], lines
        assert any("fetching 1 head failed: fatal: unable to access origin" in ln for ln in lines), lines

    def test_one_heads_failed_read_costs_only_that_pull_request(self, board, tmp_path, by_head):
        by_head.update({H1: board.Unresolvable("git diff failed: bad object"), H2: _placed("a.py", "f")})
        claims = [_claim("air", "lane/q", ["a.py"], ["a.py::f"])]
        prs = [_pr(7, "win", "lane/x", H1), _pr(8, "air-work", "lane/y", H2)]
        lines = board.overlap_lines(board.read_overlaps_section(tmp_path, "main", claims, prs,
                                                                run_=_heads({H1, H2})))
        assert any(ln.endswith("air (lane/q) and #8 air-work (lane/y) meet at a.py::f") for ln in lines), lines
        assert any("symbols not read for #7: git diff failed: bad object" in ln for ln in lines), lines

    def test_a_lane_notice_prints_only_its_own_pairs_and_the_rule(self, board, monkeypatch, tmp_path, by_head):
        """The ship notice (2-C): the pushed lane, read from its head, against
        every live claim of another seat and every open pull request. Dies to:
        the lane read from the listing (whose head lags the push), or every
        pair on the board printed."""
        by_head.update({H1: _placed("a.py", "f"), H3: _placed("c.py", "h")})
        claims = [_claim("win", "lane/y", ["a.py"], ["a.py::f"]), _claim("air", "lane/z", ["c.py"], ["c.py::h"]),
                  _claim("win-3", "lane/v", ["c.py"], ["c.py::h"])]   # a pair the lane is not in
        listed = [_pr(5, "air-work", "lane/x", "0" * 40), _pr(9, "win-2", "lane/w", H3, paths=("c.py",))]
        monkeypatch.setattr(board.mail, "machine_setting", lambda root, run=None: ("air-work", "stubbed"))
        monkeypatch.setattr(board.mail, "fetch_mail", lambda root, run=None: (True, ""))
        monkeypatch.setattr(board.mail, "read_mail", lambda root, run=None: ({}, {}))
        monkeypatch.setattr(board.mail, "live_claims", lambda by_machine: claims)
        monkeypatch.setattr(board.mail, "lane_seats", lambda by_machine: {"lane/w": "win-2"})
        monkeypatch.setattr(board, "read_open_prs", lambda root, run_=None: [dict(p) for p in listed])
        lines = board.lane_overlap_lines(tmp_path, "main", "lane/x", 7, H1, run_=_heads({H1, H3}))
        assert lines == ["overlaps: 1 pair: win (lane/y) and #7 air-work (lane/x) meet at a.py::f",
                         "          the rule stands: the second of these to merge runs the ship driver's catch-up"], lines
        by_head[H1] = _placed("d.py", "k")
        lines = board.lane_overlap_lines(tmp_path, "main", "lane/x", 7, H1, run_=_heads({H1, H3}))
        assert lines == ["overlaps: none"], lines

    def test_a_lane_notice_over_a_capped_pull_request_list_is_among_what_was_read(
            self, board, monkeypatch, tmp_path, by_head):
        """The notice reads the open pull requests to the list's limit too, so at
        the limit its none is among what was read, as the board's is. Dies to:
        the notice's none over a cut list printed as the whole."""
        by_head.update({H1: _placed("a.py", "f")})
        listed = [_pr(n, "win", f"lane/{n}", "0" * 40, paths=(f"z{n}.py",)) for n in range(board.OPEN_PR_LIMIT)]
        monkeypatch.setattr(board.mail, "machine_setting", lambda root, run=None: ("air-work", "stubbed"))
        monkeypatch.setattr(board.mail, "fetch_mail", lambda root, run=None: (True, ""))
        monkeypatch.setattr(board.mail, "read_mail", lambda root, run=None: ({}, {}))
        monkeypatch.setattr(board.mail, "live_claims", lambda by_machine: [])
        monkeypatch.setattr(board.mail, "lane_seats", lambda by_machine: {})
        monkeypatch.setattr(board, "read_open_prs", lambda root, run_=None: [dict(p) for p in listed])
        lines = board.lane_overlap_lines(tmp_path, "main", "lane/x", 7, H1, run_=_heads({H1}))
        assert lines[0] == "overlaps: none among what was read", lines
        assert any(board.OPEN_PR_CUT_NOTE in ln for ln in lines), lines

    def test_a_lane_notice_names_a_claim_of_another_rule_beside_its_own_pairs_only(
            self, board, monkeypatch, tmp_path, by_head):
        """Dies to: the ship notice dropping the rule note (the seat whose old claim keeps the
        pair unplaced is never told which claim to release), or carrying the note of a pair the
        lane is not in."""
        by_head[H1] = _placed("a.py", "f")
        claims = [_claim("win", "lane/y", ["a.py"], ["a.py::g"], rule=None),
                  _claim("air", "lane/z", ["c.py"], ["c.py::h"], rule=None),
                  _claim("win-3", "lane/v", ["c.py"], ["c.py::k"])]   # a pair the lane is not in
        self._notice_channel(board, monkeypatch, claims, [_pr(5, "air-work", "lane/x", "0" * 40)])
        lines = board.lane_overlap_lines(tmp_path, "main", "lane/x", 7, H1, run_=_heads({H1}))
        assert lines == [
            "overlaps: 1 pair: win (lane/y) and #7 air-work (lane/x) both changed a.py: unplaced lines on win's side",
            "          win (lane/y): claim c-win-lane/y was placed by another copy of tools/cc/_symbols.py and "
            "reads whole (its files as unplaced lines) until both checkouts hold the same copy (the older lane "
            "merges main, or ships) and its seat claims again",
            "          the rule stands: the second of these to merge runs the ship driver's catch-up"], lines

    def _notice_channel(self, board, monkeypatch, claims, listed):
        monkeypatch.setattr(board.mail, "machine_setting", lambda root, run=None: ("air-work", "stubbed"))
        monkeypatch.setattr(board.mail, "fetch_mail", lambda root, run=None: (True, ""))
        monkeypatch.setattr(board.mail, "read_mail", lambda root, run=None: ({}, {}))
        monkeypatch.setattr(board.mail, "live_claims", lambda by_machine: claims)
        monkeypatch.setattr(board.mail, "lane_seats", lambda by_machine: {"lane/w": "win-2"})
        monkeypatch.setattr(board, "read_open_prs", lambda root, run_=None: [dict(p) for p in listed])

    def test_a_lane_notice_reads_only_the_heads_that_can_meet_it_and_its_own_once(
            self, board, monkeypatch, tmp_path, by_head):
        """Dies to: the prefilter dropped (every open head read for a notice that prints one
        lane's pairs; a head with no table entry here raises if it is read), or the pushed head
        read twice."""
        reads: list = []
        table = {H1: _placed("a.py", "f"), H2: _placed("a.py", "f")}

        def between(base, head, **kw):
            reads.append(head)
            return table[head]

        monkeypatch.setattr(board._symbols, "symbols_between", between)
        listed = [_pr(8, "win-2", "lane/w", H2), _pr(9, "air", "lane/z", H3, paths=("c.py",))]
        self._notice_channel(board, monkeypatch, [], listed)
        lines = board.lane_overlap_lines(tmp_path, "main", "lane/x", 7, H1, run_=_heads({H1, H2, H3}))
        assert lines[0] == "overlaps: 1 pair: #7 air-work (lane/x) and #8 win-2 (lane/w) meet at a.py::f", lines
        assert sorted(reads) == [H1, H2], reads

    def test_a_lane_notice_reads_a_pull_request_at_githubs_file_cap(self, board, monkeypatch, tmp_path, by_head):
        """Dies to: the prefilter trusting a capped list (the meeting file past GitHub's 100th
        never listed, so the notice said none where the board read the pair)."""
        by_head.update({H1: _placed("z.py", "f"), H2: _placed("z.py", "f")})
        capped = _pr(8, "win-2", "lane/w", H2, paths=tuple(f"f{i}.py" for i in range(board.GH_FILES_CAP)))
        self._notice_channel(board, monkeypatch, [], [capped])
        lines = board.lane_overlap_lines(tmp_path, "main", "lane/x", 7, H1, run_=_heads({H1, H2}))
        assert lines[0] == "overlaps: 1 pair: #7 air-work (lane/x) and #8 win-2 (lane/w) meet at z.py::f", lines

    def test_a_pair_with_no_symbols_ranks_above_a_certificate(self, board, tmp_path, by_head):
        """Dies to: prose and whole-folder pairs sorted under the certificates (the pairs that
        can conflict at catch-up hidden past the cap)."""
        claims = [_claim("win", "lane/x", ["a.py"], ["a.py::f"]), _claim("air-work", "lane/y", ["a.py"], ["a.py::g"]),
                  _claim("s1", "lane/1", ["docs/x.md"]), _claim("s2", "lane/2", ["docs/x.md"])]
        got = board.read_overlaps_section(tmp_path, "main", claims, [], run_=_heads(set()))
        assert [p["verdict"] for p in got["pairs"]] == ["path only", "different functions"], got["pairs"]

    def test_a_lane_notice_says_what_it_could_not_read(self, board, monkeypatch, tmp_path, by_head):
        by_head[H1] = _placed("a.py", "f")
        failed = f"{board.mail.MACHINE_UNREAD} (git config exited 1)"
        monkeypatch.setattr(board.mail, "machine_setting", lambda root, run=None: ("", failed))
        monkeypatch.setattr(board.mail, "fetch_mail", lambda root, run=None: (False, "origin unreachable"))

        def unread(root, run=None):
            raise board.Unresolvable("the mail refs are corrupt")

        monkeypatch.setattr(board.mail, "read_mail", unread)

        def no_prs(root, run_=None):
            raise board.Unresolvable("gh pr list took longer than 15s")

        monkeypatch.setattr(board, "read_open_prs", no_prs)
        lines = board.lane_overlap_lines(tmp_path, "main", "lane/x", 7, H1, run_=_heads({H1}))
        assert lines[0] == "overlaps: none among what was read", lines
        assert any(f"seat name could not be read ({failed})" in ln for ln in lines), lines
        assert any("the claims are unread (the mail refs are corrupt)" in ln for ln in lines), lines
        assert any("the open pull requests are unread (gh pr list took longer than 15s)" in ln for ln in lines), lines

    @pytest.mark.parametrize("hand", ["src/a.py", "src"], ids=["file", "folder"])
    def test_a_path_claimed_by_hand_stays_whole_beside_a_later_symbol_claim(self, board, tmp_path, by_head, hand):
        """Dies to: the lane's claims united before each is read (a file given
        by hand, then a --delta claim naming one symbol in it, read as the
        whole list: the board certified where mail withheld it)."""
        claims = [_claim("win", "lane/x", [hand]), _claim("win", "lane/x", ["src/a.py"], ["src/a.py::f"]),
                  _claim("air-work", "lane/y", ["src/a.py"], ["src/a.py::g"])]
        lines = board.overlap_lines(board.read_overlaps_section(tmp_path, "main", claims, [], run_=_heads(set())))
        assert lines == ["overlaps: 1 pair: win (lane/x) and air-work (lane/y) both changed src/a.py: "
                         "unplaced lines on win's side"], lines

    def test_a_shared_prose_file_is_kept_beside_the_certificate(self, board, tmp_path, by_head):
        """Dies to: the files not Python dropped from a certified pair (the one
        that can conflict at catch-up would read as safe)."""
        claims = [_claim("win", "lane/x", ["a.py", "docs/x.md"], ["a.py::f"]),
                  _claim("air-work", "lane/y", ["a.py", "docs/x.md"], ["a.py::g"])]
        lines = board.overlap_lines(board.read_overlaps_section(tmp_path, "main", claims, [], run_=_heads(set())))
        assert lines == ["overlaps: 1 pair: win (lane/x) and air-work (lane/y) both changed a.py: different functions, "
                         "none shared or next to the other's; also both changed docs/x.md "
                         "(no symbols: not Python, or a folder claimed whole)"], lines

    def test_a_meeting_in_a_run_of_blank_lines_is_said_in_words(self, board, tmp_path, by_head):
        claims = [_claim("win", "lane/x", ["a.py"], ["a.py::<after:TestA.test_one>", "a.py::TestA.test_a"]),
                  _claim("air-work", "lane/y", ["a.py"], ["a.py::<after:TestA.test_one>", "a.py::TestA.test_b"])]
        lines = board.overlap_lines(board.read_overlaps_section(tmp_path, "main", claims, [], run_=_heads(set())))
        assert lines == ["overlaps: 1 pair: win (lane/x) and air-work (lane/y) meet at the blank lines after "
                         "a.py::TestA.test_one"], lines

    def test_a_meeting_at_the_end_of_a_file_is_said_in_words(self, board, tmp_path, by_head):
        claims = [_claim("win", "lane/x", ["a.py"], ["a.py::<end>", "a.py::h1"]),
                  _claim("air-work", "lane/y", ["a.py"], ["a.py::<end>", "a.py::h2"])]
        lines = board.overlap_lines(board.read_overlaps_section(tmp_path, "main", claims, [], run_=_heads(set())))
        assert lines == ["overlaps: 1 pair: win (lane/x) and air-work (lane/y) meet at the end of a.py"], lines

    def test_a_pull_request_read_from_nothing_is_a_note_never_silence(self, board, tmp_path, by_head):
        """Dies to: an unread side with no file listed dropped (no pair forms,
        and the section said none over a lane it never read)."""
        claims = [_claim("air-work", "lane/y", ["a.py"], ["a.py::g"])]
        got = board.read_overlaps_section(tmp_path, "main", claims, [_pr(7, "win", "lane/x", H1, paths=())],
                                          run_=_heads(set()))
        lines = board.overlap_lines(got)
        assert lines[0] == "overlaps: none among what was read", lines
        assert any("#7: symbols not read (head not here) and no file listed" in ln for ln in lines), lines

    def test_a_lane_notice_whose_own_head_cannot_be_read_says_so(self, board, monkeypatch, tmp_path, by_head):
        """Dies to: the pushed lane's unread side read as no overlap (a false
        all-clear printed after every push whose head diff timed out)."""
        by_head[H1] = board.Unresolvable("git diff took longer than 30s")
        monkeypatch.setattr(board.mail, "machine_setting", lambda root, run=None: ("air-work", "stubbed"))
        lines = board.lane_overlap_lines(tmp_path, "main", "lane/x", 7, H1, run_=_heads({H1}))
        assert lines == ["overlaps: unread (the pushed head 1111111 could not be read: git diff took longer than "
                         "30s)"], lines

    def test_no_fetch_reads_the_heads_as_they_are_here(self, board, monkeypatch, tmp_path):
        """Dies to: the head fetch run under --no-fetch (an offline seat's quick
        read reached the network), or after the stale section."""
        _stub_channel(monkeypatch, board)
        monkeypatch.setattr(board, "read_overlaps_section", TestOverlapsSection._real_section)
        calls: list = []
        pr = {"number": 7, "headRefName": "lane/x", "headRefOid": H1, "mergeStateStatus": "BLOCKED",
              "isDraft": False, "autoMergeRequest": None, "files": [{"path": "a.py"}]}
        gh = _gh({"pr list": [pr], "run list": _GREEN_RUNS})

        def run(argv, **kw):
            calls.append(list(argv))
            if argv[0] == "git":
                return (1, "", "") if argv[1] == "cat-file" else (0, "", "")
            return gh(argv, **kw)

        board.collect(tmp_path, fetch=False, run_=run, now=_NOW)
        assert not [c for c in calls if c[:2] == ["git", "fetch"]], calls

    def test_another_seats_claim_on_the_pull_requests_lane_name_stays_a_side(self, board, tmp_path, by_head):
        """Dies to: every claim on a pull request's lane name dropped (another
        seat's claim there, a real meeting, read as none)."""
        by_head[H1] = _placed("b.py", "k")
        claims = [_claim("air-work", "lane/x", ["a.py"], ["a.py::f"]), _claim("air", "lane/q", ["a.py"], ["a.py::f"])]
        got = board.read_overlaps_section(tmp_path, "main", claims, [_pr(7, "win", "lane/x", H1, paths=("b.py",))],
                                          run_=_heads({H1}))
        assert "overlaps: 1 pair: air-work (lane/x) and air (lane/q) meet at a.py::f" in board.overlap_lines(got)

    def test_a_head_not_here_at_githubs_file_cap_says_more_may_meet(self, board, tmp_path, by_head):
        paths = tuple(f"f{i}.py" for i in range(board.GH_FILES_CAP))
        got = board.read_overlaps_section(tmp_path, "main", [], [_pr(7, "win", "lane/x", H1, paths=paths)],
                                          run_=_heads(set()))
        assert any(f"at most {board.GH_FILES_CAP} files" in n for n in got["notes"]), got["notes"]

    def test_the_pairs_a_seat_must_answer_come_first(self, board, tmp_path, by_head):
        """Dies to: the pairs left in reading order before the cap (a meeting in
        one function folded behind a dozen prose pairs)."""
        claims = [_claim(f"s{i}", f"lane/{i}", ["docs/x.md"]) for i in range(board.OVERLAPS_SHOWN)]
        claims += [_claim("win", "lane/x", ["a.py"], ["a.py::f"]), _claim("air-work", "lane/y", ["a.py"], ["a.py::f"])]
        got = board.read_overlaps_section(tmp_path, "main", claims, [], run_=_heads(set()), seat="win")
        assert board.overlap_lines(got)[0] == "overlaps: 67 pairs: win (lane/x) and air-work (lane/y) meet at a.py::f"

    def test_a_pull_request_no_claim_names_is_labelled_so(self, board, tmp_path, by_head):
        """Dies to: an unattributed pull request labelled as nobody's (its own
        seat's claim then reads as another seat meeting it)."""
        by_head[H1] = _placed("a.py", "f")
        got = board.read_overlaps_section(tmp_path, "main", [_claim("win", "lane/y", ["a.py"], ["a.py::f"])],
                                          [_pr(7, "", "lane/x", H1)], run_=_heads({H1}))
        assert board.overlap_lines(got) == [
            "overlaps: 1 pair: win (lane/y) and #7 (lane/x; no seat's claim names it) meet at a.py::f"]

    def test_every_verdict_the_mapper_gives_has_its_words_and_its_place(self, board):
        """Dies to: a new verdict worded as prose (a fallback 'not Python' over a
        Python file) or sorted nowhere."""
        assert set(board._symbols.VERDICTS) <= set(board._VERDICT_ORDER)
        for verdict in board._symbols.VERDICTS:
            text = board._overlap_text({"a": "A", "b": "B", "verdict": verdict, "files": ["a.py"],
                                        "shared": ["a.py::f"], "paths": [], "unplaced_on": []})
            assert text.startswith("A and B"), text
            assert verdict == "path only" or "(no symbols" not in text, (verdict, text)

    def test_the_lines_are_ascii(self, board, tmp_path, by_head):
        claims = [_claim("win", "lane/x", ["docs/café.md"]), _claim("air-work", "lane/y", ["docs/café.md"])]
        lines = board.overlap_lines(board.read_overlaps_section(tmp_path, "main", claims, [], run_=_heads(set())))
        assert lines and all(ln.isascii() for ln in lines), lines

    def test_the_call_into_the_mapper_matches_its_signature(self, board):
        """Dies to: a renamed keyword on either side (every stubbed row stays
        green while each real read fails as a TypeError)."""
        import inspect

        inspect.signature(board._symbols.symbols_between).bind("b" * 40, H1, root=Path("."), run=None, env=None)

    @staticmethod
    def _real_section(*a, **k):
        return _REAL_SECTION(*a, **k)

    def test_the_rows_stamp_the_mappers_rule(self, board):
        assert _RULE == board._symbols.RULE and board.mail.SYMBOLS_RULE_KEY == "symbols_rule"

    @pytest.mark.parametrize("rule", [None, "0" * 16, 3], ids=["unstamped", "another-source", "a-number"])
    def test_a_claim_of_another_rule_never_certifies(self, board, tmp_path, by_head, rule):
        """Dies to: a claim from before the neighbour rule, or from a newer mapper, read as a
        complete list (it names `C.o` alone for a method appended to a class, with no mark for the
        run of blanks it landed in; another seat's head appending `C.p` there meets it, and git
        conflicts); or its seat not told which claim to release, the line naming only unplaced
        lines it never left (the code review of Wave 2's last delta, driven)."""
        by_head[H1] = {"p.py": {"kind": "python", "symbols": {"p.py::C.p", "p.py::<after:C.n>"}, "changed": 2,
                                "unplaced": 0, "beside": 0}}
        old = _claim("air-work", "lane/y", ["p.py"], ["p.py::C.o"], rule=rule)
        got = board.read_overlaps_section(tmp_path, "main", [old], [_pr(7, "win", "lane/x", H1, paths=("p.py",))],
                                          run_=_heads({H1}))
        assert got["pairs"][0]["verdict"] == "unplaced", got["pairs"]
        lines = board.overlap_lines(got)
        assert lines[1:] == ["          air-work (lane/y): claim c-air-work-lane/y was placed by another copy of "
                             "tools/cc/_symbols.py and reads whole (its files as unplaced lines) until both "
                             "checkouts hold the same copy (the older lane merges main, or ships) and its seat "
                             "claims again"], lines
        assert not got["partial"], got   # read whole is read: nothing is missing
        assert board.overlap_lines({**got, "pairs": []}) == ["overlaps: none"]   # said beside its pairs only
        stamped = _claim("air-work", "lane/y", ["p.py"], ["p.py::C.o", "p.py::<after:C.n>"])
        got = board.read_overlaps_section(tmp_path, "main", [stamped], [_pr(7, "win", "lane/x", H1, paths=("p.py",))],
                                          run_=_heads({H1}))
        assert got["pairs"][0]["verdict"] == "shared symbol", got["pairs"]
        assert not any("another copy" in line for line in board.overlap_lines(got))

    def test_the_rule_note_stays_beside_a_shown_pair_its_claim_declines(self, board):
        """Dies to: the note said beside a pair a release and a new claim cannot change (a
        meeting), or beside one hidden past the cap, or for a side the pair does not decline on
        (the code review of Wave 2's last delta: the cap's case survived as a mutant)."""
        def pair(a, verdict, on=()):
            return {"a": a, "b": "#7 win (lane/x)", "verdict": verdict, "files": ["p.py"], "paths": [],
                    "shared": ["p.py::f"] if verdict == "shared symbol" else [], "not_read": "",
                    "unplaced_on": [s.split()[0] for s in on], "unplaced_labels": list(on)}

        fill = [pair(f"x{i} (lane/z)", "unplaced", on=["#7 win (lane/x)"]) for i in range(board.OVERLAPS_SHOWN - 2)]
        section = {"pairs": [pair("s (lane/a)", "unplaced", on=["s (lane/a)"]), pair("m (lane/b)", "shared symbol"),
                             *fill, pair("h (lane/c)", "unplaced", on=["h (lane/c)"])],
                   "notes": [], "partial": False,
                   "stale_rule": {"s (lane/a)": ["c-1", "c-9"], "m (lane/b)": ["c-2"], "h (lane/c)": ["c-3"],
                                  "x0 (lane/z)": ["c-4"]}}
        notes = [line.strip() for line in board.overlap_lines(section) if "another copy" in line]
        assert notes == ["s (lane/a): claims c-1, c-9 were placed by another copy of tools/cc/_symbols.py and read "
                         "whole (their files as unplaced lines) until both checkouts hold the same copy (the older "
                         "lane merges main, or ships) and their seat claims again"], notes

    def test_no_rule_note_beside_a_pair_the_older_claim_does_not_decline(self, board, tmp_path, by_head):
        """Through the section, not a hand-built pair. Dies to: a pair's declining sides named as
        both (a lane whose older claim is on another file gets the note beside a pair a release
        cannot change; the code review of Wave 2's sixth delta, driven)."""
        claims = [_claim("air-work", "lane/y", ["a.py"], ["a.py::f"]),
                  _claim("air-work", "lane/y", ["b.py"], ["b.py::g"], rule=None),
                  _claim("win", "lane/x", ["a.py"])]
        got = board.read_overlaps_section(tmp_path, "main", claims, [], run_=_heads(set()))
        (pair,) = got["pairs"]
        assert pair["verdict"] == "unplaced" and pair["unplaced_labels"] == ["win (lane/x)"], pair
        assert not any("another copy" in line for line in board.overlap_lines(got))

    def test_a_side_that_declines_on_an_insertion_naming_no_point_is_named(self, board, tmp_path, by_head):
        """Dies to: the side-naming left untaught of `beside` (the line said unplaced lines and
        named nobody's side)."""
        by_head[H1] = {"a.py": {"kind": "python", "symbols": {"a.py::h", "a.py::<module>"}, "changed": 2,
                                "unplaced": 0, "beside": 1}}
        claims = [_claim("air-work", "lane/y", ["a.py"], ["a.py::g"])]
        lines = board.overlap_lines(board.read_overlaps_section(
            tmp_path, "main", claims, [_pr(7, "win", "lane/x", H1)], run_=_heads({H1})))
        assert lines == ["overlaps: 1 pair: air-work (lane/y) and #7 win (lane/x) both changed a.py: "
                         "unplaced lines on #7's side"], lines

    def test_the_section_reaches_the_board(self, board, monkeypatch, tmp_path):
        _stub_channel(monkeypatch, board)
        section = {"pairs": [{"a": "win (lane/x)", "b": "air-work (lane/y)", "verdict": "shared symbol",
                              "files": ["a.py"], "shared": ["a.py::f"], "unplaced_on": [], "not_read": ""}],
                   "notes": []}
        monkeypatch.setattr(board, "read_overlaps_section", lambda *a, **k: section)
        collected = board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS}), now=_NOW)
        json.dumps(collected)
        assert "overlaps: 1 pair: win (lane/x) and air-work (lane/y) meet at a.py::f" in board.render(collected).splitlines()


class TestTheReadingsAreTheProtocols:
    """The parallel-work protocol retired the dispatcher's hand read of two lanes' hunks (TP-702
    Wave 3), so the readings it and /inbox's Step 2c list are the rule a seat reads the board by:
    each verdict the board renders has its words in both, and the protocol says which is the
    certificate. ``none`` is ``pair_verdict``'s answer for no file in common, which the board never
    pairs."""

    WORDS = {"shared symbol": "meet at", "not read": "symbols not read", "unplaced": "unplaced lines",
             "path only": "no symbols", "different functions": "different functions"}

    @pytest.mark.contract
    def test_every_reading_the_board_renders_is_named_where_seats_read_it(self, board):
        """Dies to: a verdict the board renders that the protocol or /inbox does not name (the
        failure-mode review found `symbols not read` missing from the protocol), or a word here
        the board no longer prints."""
        assert set(self.WORDS) == set(board._VERDICT_ORDER) - {"none"}
        for verdict, words in self.WORDS.items():
            pair = {"a": "win (lane/x)", "b": "air-work (lane/y)", "verdict": verdict, "files": ["a.py"],
                    "shared": ["a.py::f"], "paths": [], "unplaced_on": [], "not_read": "#7"}
            assert words in board._overlap_text(pair), (verdict, board._overlap_text(pair))
        for doc in ("memory/parallel-work-protocol.md", ".claude/commands/inbox.md"):
            text = (REPO_ROOT / doc).read_text(encoding="utf-8")
            assert not [w for w in self.WORDS.values() if f"`{w}" not in text], doc
        protocol = (REPO_ROOT / "memory" / "parallel-work-protocol.md").read_text(encoding="utf-8")
        assert "`different functions` is the certificate" in protocol


class TestSectionCounts:
    """Every list section's first line names its count, so a reader that keeps
    only the header line still sees how many there are (on 2026-10-18 a line
    filter cut ``jobs:`` from six rows to two, and the under-read looked like a
    board defect). Each count is the length of the list the section renders,
    computed where it renders and never stored on the board."""

    @staticmethod
    def _board(**kw) -> dict:
        year = 365 * 86400  # past any quiet threshold the board folds at
        built = {
            "read_at": "2026-10-20T00:00:00Z", "dispatcher": {"name": "air"},
            "open_prs": [{"number": 1, "headRefName": "lane/a", "seat": "win"},
                         {"number": 2, "headRefName": "lane/b", "seat": "win-2"}],
            "seats": {"rows": [{"name": "win", "last_mail": {"age_s": 60}},
                               {"name": "win-2", "last_mail": {"age_s": 60}},
                               {"name": "gone", "last_mail": {"age_s": year}}]},
            "assignments": [{"id": "a1", "at": "t0", "re": {"seat": "win", "lane": "lane/a"}},
                            {"id": "a2", "at": "t0", "re": {"seat": "win-2", "ids": ["DEF-1"]}}],
            "claims": [{"from": "win", "at": "t0", "re": {"lane": "lane/a", "paths": ["a.py"]}},
                       {"from": "win-2", "at": "t0", "re": {"lane": "lane/b", "paths": ["b.py"]}}],
            "records": {"window": 100, "unread": "", "read": 40, "unclaimed": 0,
                        "entries": [{"seat": "win", "merges": 3, "since": "2026-10-18", "parked": False, "cut": False},
                                    {"seat": "win-2", "merges": 0, "since": "2026-10-20", "parked": True, "cut": False}]},
            "overlaps": {"pairs": [
                {"a": "win (lane/a)", "b": "win-2 (lane/b)", "files": ["a.py"], "verdict": "path only"},
                {"a": "win (lane/a)", "b": "air (lane/c)", "files": ["c.py"], "verdict": "path only"}]},
            # A stale stored count a renderer must never read.
            "jobs_count": 6, "claims_count": 6, "seats_count": 6,
        }
        built.update(kw)
        return built

    def test_every_list_header_names_the_length_of_its_list(self, board):
        """Dies to: a count read from a stored field, or a seat count that
        leaves the folded quiet seat out."""
        text = board.render(self._board())
        assert "open PRs: 2 open: #1 lane/a [win]" in text, text
        assert "seats:    3 seats: " in text, text
        assert "and 1 seat with no mail in" in text, text
        assert "jobs:     (dispatcher air) 2 live: win: " in text, text
        assert "claims:   2 live: win: lane/a" in text, text
        assert "records:  2 seats: win: 3 merges since its last row (2026-10-18)" in text, text
        assert "overlaps: 2 pairs: win (lane/a) and win-2 (lane/b) both changed a.py" in text, text

    def test_an_empty_section_keeps_its_none_form(self, board):
        """Dies to: a count printed on a section with nothing in it."""
        text = board.render(self._board(open_prs=[], assignments=[], claims=[], overlaps={"pairs": []},
                                        seats={"rows": []}, records={"window": 100, "unread": "", "entries": []}))
        for line in ("open PRs: none", "jobs:     (dispatcher air) no live assignments", "claims:   none live",
                     "overlaps: none", "seats:    none: no machine has mail", "records:  none (no seat has"):
            assert line in text, (line, text)

    def test_the_jobs_count_is_the_length_of_the_assignments_list(self, board, monkeypatch, tmp_path, capsys):
        """The re-measure's pin: ``jobs: N live`` equals the length of the list
        ``mail.py assignments --json`` prints over the same refs. Dies to: a
        filter or a dispatcher read in the board that the verb lacks, or in the
        verb that the board lacks."""
        mail = board.mail
        t = datetime(2026, 10, 9, 20, 0, 0, tzinfo=timezone.utc)
        jobs = [mail.new_message("air", "assign", "", seat="win", lane=f"lane/{n}", now=t) for n in "abc"]
        self_made = mail.new_message("win-2", "assign", "", seat="win-2", lane="lane/self", now=t)
        _stub_channel(monkeypatch, board, {"air": jobs, "win-2": [self_made]})
        assert mail.main(["--root", str(tmp_path), "assignments", "--json", "--no-fetch"]) == 0
        verb = json.loads(capsys.readouterr().out)
        collected = board.collect(tmp_path, run_=_gh({"pr list": [], "run list": _GREEN_RUNS}))
        assert len(verb) == len(collected["assignments"]) == 3
        assert f"jobs:     (dispatcher air) {len(verb)} live: " in board.render(collected)

    def test_a_partial_or_capped_read_says_so_beside_its_count(self, board):
        """A count over a list the read may have cut reads as the whole. Dies
        to: ``overlaps: 1 pair`` on a partial read, or ``open PRs: 30 open`` at
        the read's limit."""
        partial = board.overlap_lines({"partial": True, "pairs": [
            {"a": "win (lane/a)", "b": "win-2 (lane/b)", "files": ["a.py"], "verdict": "path only"}]})
        assert partial[0].startswith("overlaps: 1 pair among what was read: "), partial
        capped = [{"number": n, "headRefName": f"lane/{n}", "seat": "win"} for n in range(board.OPEN_PR_LIMIT)]
        text = board.render(self._board(open_prs=capped))
        assert f"open PRs: {board.OPEN_PR_LIMIT}+ open (the first {board.OPEN_PR_LIMIT}): #0 " in text, text

    def test_the_overlaps_of_a_capped_pull_request_list_are_among_what_was_read(self, board, monkeypatch, tmp_path):
        """The overlaps are read over the open pull requests the list returned;
        at the read's limit some may be cut, so the section is partial and says
        why. Dies to: the overlaps of a cut list counted as the whole."""
        _stub_channel(monkeypatch, board, {})
        monkeypatch.setattr(board, "read_overlaps_section", lambda *a, **kw: {"pairs": [], "notes": [], "partial": False})
        monkeypatch.setattr(board, "read_stale_section", lambda *a, **kw: None)
        for n, partial in ((board.OPEN_PR_LIMIT - 1, False), (board.OPEN_PR_LIMIT, True)):
            prs = [{"number": i, "headRefName": f"lane/{i}", "headRefOid": "", "files": []} for i in range(n)]
            collected = board.collect(tmp_path, fetch=False, run_=_gh({"pr list": prs, "run list": _GREEN_RUNS}))
            assert collected["overlaps"]["partial"] is partial, (n, collected["overlaps"])
            assert any(f"the first {board.OPEN_PR_LIMIT}" in note for note in collected["overlaps"]["notes"]) is partial
