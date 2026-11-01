"""Contract tests for ``tools/cc/_post_merge.py``: the one home of the
post-merge check verdicts the ship preflight, the SessionStart banner's
``Merged:`` line and the board's ``checks:`` line read. This file pins the
rule there because three readers once kept three copies of it that drifted
in their windows, their ownership and their words, and the drift is what
left a Windows red unread for six hours; each test names the mutation it
dies to, so a copy returning or a gate dropped reds here.

The oracle is the frozen rollup of pull requests #312 and #313 (2026-10-18):
#313 merged 13:26:32Z with its Windows leg red (completed 13:57:44Z, a run that
started 12:36:26Z, before #312 merged); #312 merged 13:01:07Z with its Windows
leg green from a run that started 12:45:40Z and finished 14:10:49Z, after #313
had merged. Merge order alone cannot say which verdict stands; the ownership
rule can, and these tests drive it both ways.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE = REPO_ROOT / "tools" / "cc" / "_post_merge.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "post_merge"


def _load(path: Path, alias: str):
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pm():
    return _load(MODULE, "post_merge_under_test")


def _pr(n: int) -> dict:
    return json.loads((FIXTURES / f"pr{n}.json").read_text(encoding="utf-8"))


def _leg(pr: dict, name: str) -> dict:
    rows = [r for r in pr["statusCheckRollup"] if r.get("name") == name]
    assert len(rows) == 1, (pr["number"], name, len(rows))
    return rows[0]


def _row(name: str, started: str, completed: str | None, conclusion: str | None, status: str = "COMPLETED") -> dict:
    return {"__typename": "CheckRun", "name": name, "startedAt": started, "completedAt": completed,
            "status": status, "conclusion": conclusion}


WIN = "portability (windows-latest)"
MAC = "portability (macos-latest)"


class TestTheSetsAndTheOutcome:
    def test_the_check_state_sets_are_the_banners_literals(self, pm):
        """Dies to: a set widened or narrowed in the one home (the banner and
        the driver read these through it, so the literals are pinned here)."""
        assert pm.CHECK_GREEN == frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})
        assert pm.CHECK_RUNNING == frozenset({"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"})
        assert pm.NO_VERDICT == frozenset({"CANCELLED", "STALE"})
        assert pm.RED_BUCKETS == frozenset({"fail", "cancel"})

    def test_check_outcome_reads_contexts_runs_and_unknown_shapes(self, pm):
        """Dies to: an unknown shape read as a pass, or a context's state ignored."""
        assert pm.check_outcome({"state": "SUCCESS"}) == "green"
        assert pm.check_outcome({"state": "PENDING"}) == "running"
        assert pm.check_outcome({"state": "ERROR"}) == "red"
        assert pm.check_outcome(_row("x", "", None, None, status="IN_PROGRESS")) == "running"
        assert pm.check_outcome(_row("x", "", "", "FAILURE")) == "red"
        assert pm.check_outcome(_row("x", "", "", "SKIPPED")) == "green"
        assert pm.check_outcome(_row("x", "", "", "CANCELLED")) == "red"
        assert pm.check_outcome("not a row") == "running"
        assert pm.check_outcome({}) == "running"

    def test_latest_run_per_check_keeps_the_latest_started_run(self, pm):
        """Dies to: the superseded run kept, or a nameless row dropped."""
        rows = [_row("a", "2026-01-01T10:00:00Z", "", "FAILURE"), _row("a", "2026-01-01T11:00:00Z", "", "SUCCESS"), {"status": "x"}]
        kept = pm.latest_run_per_check(rows)
        assert [r.get("conclusion") for r in kept] == ["SUCCESS", None]


class TestTheOwnershipRuleOnTheMeasuredMerges:
    def test_the_measured_fixture_names_313_red_since_and_312_green_on(self, pm):
        """The Windows leg: red on #313 (the newer merge), green on #312 from a
        run that started before #313 merged, so the green predates the red and
        the red stands. Dies to: ownership read oldest-first (names #312), or
        the green on #312 lost."""
        checks = pm.transitions([_pr(312), _pr(313)])
        win = checks[WIN]
        assert win["verdict"] == "red" and win["owner"]["pr"] == 313
        assert win["since"]["pr"] == 313 and win["since"]["merged_at"] == "2026-10-18T13:26:32Z"
        assert win["since"]["completed_at"] == "2026-10-18T13:57:44Z"
        assert win["previous"] and win["previous"]["pr"] == 312 and win["previous"]["verdict"] == "green"
        mac = checks[MAC]
        assert mac["verdict"] == "red" and mac["since"]["pr"] == 312 and mac["previous"] is None
        assert checks["portability (ubuntu-latest)"]["verdict"] == "green"

    def test_a_green_that_started_before_the_red_merge_does_not_clear_it(self, pm):
        """The verdicts swapped: red on #312, green on #313 from a run that
        started 12:36:26Z, before #312 merged at 13:01:07Z. Dies to: the
        startedAt gate dropped (the green clears the red)."""
        a, b = copy.deepcopy(_pr(312)), copy.deepcopy(_pr(313))
        _leg(a, WIN)["conclusion"] = "FAILURE"
        _leg(b, WIN)["conclusion"] = "SUCCESS"
        assert _leg(b, WIN)["startedAt"] < a["mergedAt"]
        win = pm.transitions([a, b])[WIN]
        assert win["verdict"] == "red" and win["owner"]["pr"] == 312 and win["since"]["pr"] == 312
        assert [g["pr"] for g in win["green_beside"]] == [313]

    def test_a_green_that_started_after_the_red_merge_clears_it(self, pm):
        """Dies to: a green that contained the red merge refused ownership."""
        a, b = copy.deepcopy(_pr(312)), copy.deepcopy(_pr(313))
        _leg(a, WIN)["conclusion"] = "FAILURE"
        _leg(b, WIN).update(conclusion="SUCCESS", startedAt="2026-10-18T13:05:00Z", completedAt="2026-10-18T14:00:00Z")
        win = pm.transitions([a, b])[WIN]
        assert win["verdict"] == "green" and win["owner"]["pr"] == 313 and win["green_beside"] == []

    def test_a_cancelled_latest_run_on_a_newer_merge_is_named_beside_the_red(self, pm):
        """Dies to: a cancelled run read as a verdict (green or red), or not named."""
        a, b, c = copy.deepcopy(_pr(312)), copy.deepcopy(_pr(313)), copy.deepcopy(_pr(313))
        c.update(number=320, mergedAt="2026-10-18T15:00:00Z")
        _leg(c, WIN).update(conclusion="CANCELLED", startedAt="2026-10-18T14:30:00Z", completedAt="2026-10-18T14:31:00Z")
        win = pm.transitions([a, b, c])[WIN]
        assert win["verdict"] == "red" and win["since"]["pr"] == 313
        assert [(n["pr"], n["conclusion"]) for n in win["no_verdict"]] == [(320, "cancelled")]

    def test_a_row_without_merged_at_sorts_oldest_in_listing_order_and_gets_no_since_clause(self, pm):
        """The ship preflight's own fixture carries no mergedAt. Dies to: a
        missing stamp crashing the sort, or a since clause invented for it."""
        rows = [{"number": 41, "statusCheckRollup": [_row("portability", "2026-09-29T10:00:00Z", "", "SUCCESS"),
                                                     _row("portability", "2026-09-29T11:00:00Z", "", "FAILURE")]}]
        checks = pm.transitions(rows)
        assert checks["portability"]["verdict"] == "red"
        assert pm.lines(checks, oldest=41) == ["red after merge: #41 portability"]


class TestTheWindowsEdge:
    def test_the_oldest_merge_is_the_earliest_stamp_never_the_lowest_number(self, pm):
        """Pull requests merge out of number order. Dies to: oldest keyed on the
        number (a red on a low-numbered lane merged last would read as older
        than the window, and the window's true first merge would get a dated
        origin it cannot have)."""
        late_low = copy.deepcopy(_pr(312))
        late_low.update(number=301, mergedAt="2026-10-18T16:00:00Z")
        assert pm.oldest_merge([late_low, _pr(313)]) == 313
        assert pm.oldest_merge([{"number": 5}, _pr(313)]) == 5   # no stamp: oldest, as the walk reads it
        assert pm.oldest_merge([]) is None
        checks = pm.transitions([late_low, _pr(313)])
        # #313 is the earliest merge read, so its red has no dated origin: with
        # the lowest NUMBER (#301) as "oldest" the line would have claimed one.
        assert "since #313 or earlier (the oldest merge read)" in pm.lines(checks, oldest=313)[0]
        assert any("since #313 or earlier" in line for line in pm.board_lines(checks, window=2, oldest=313))
        dated = pm.lines(checks, oldest=301)[0]
        assert "or earlier" not in dated and "since 2026-10-18 13:26Z" in dated   # the false origin the number would print

    def test_a_skipped_run_tests_nothing_and_clears_no_red(self, pm):
        """A path-filtered leg skips on a docs-only merge. Dies to: SKIPPED read
        as a green verdict that clears the older red."""
        a, b = copy.deepcopy(_pr(313)), copy.deepcopy(_pr(313))
        b.update(number=320, mergedAt="2026-10-18T15:00:00Z")
        _leg(b, WIN).update(conclusion="SKIPPED", startedAt="2026-10-18T14:30:00Z")
        win = pm.transitions([a, b])[WIN]
        assert win["verdict"] == "red" and win["owner"]["pr"] == 313 and win["running"] == []

    def test_a_check_judged_on_no_merge_is_named_never_green(self, pm):
        """Dies to: an all-cancelled check folded into `none red`."""
        a = copy.deepcopy(_pr(313))
        for leg in (WIN, MAC):
            _leg(a, leg)["conclusion"] = "CANCELLED"
        checks = pm.transitions([a])
        assert checks[WIN]["verdict"] is None
        board = pm.board_lines(checks, window=1, oldest=313)
        assert f"{WIN}: no verdict on every merge read (cancelled)" in board and "none red" not in " ".join(board)
        assert any(line.startswith(f"no verdict after merge: {WIN} (cancelled on #313") for line in pm.lines(checks))

    def test_a_new_owner_starts_its_own_beside_lists(self, pm):
        """Dies to: a green beside an older red carried onto a newer red's line."""
        a, b, c = copy.deepcopy(_pr(312)), copy.deepcopy(_pr(313)), copy.deepcopy(_pr(313))
        _leg(a, WIN)["conclusion"] = "FAILURE"                        # red on #312
        _leg(b, WIN)["conclusion"] = "SUCCESS"                        # green on #313 from a run that predates #312's merge
        c.update(number=320, mergedAt="2026-10-18T15:00:00Z")
        _leg(c, WIN).update(conclusion="FAILURE", startedAt="2026-10-18T14:30:00Z")   # red again on #320
        win = pm.transitions([a, b, c])[WIN]
        assert win["owner"]["pr"] == 320 and win["since"]["pr"] == 312 and win["green_beside"] == []

    def test_new_names_are_marked_on_the_board(self, pm):
        checks = pm.transitions([_pr(312), _pr(313)])
        lines = pm.board_lines(checks, window=2, oldest=312, new={WIN})
        assert lines[0].startswith(f"new: {WIN}: red since #313") and not lines[1].startswith("new:")


class TestReplayAtAnInstant:
    def test_at_14_00_the_312_leg_is_running_and_at_14_15_it_is_green_on(self, pm):
        """The roadmap's oracle. Dies to: a completedAt after the instant read
        as a verdict (14:00 would already say green on #312), or a run that
        started after the instant kept."""
        early = pm.transitions([_pr(312), _pr(313)], at="2026-10-18T14:00:00Z")[WIN]
        assert early["verdict"] == "red" and early["since"]["pr"] == 313
        assert early["previous"] is None and early["running"] == [312]
        late = pm.transitions([_pr(312), _pr(313)], at="2026-10-18T14:15:00Z")[WIN]
        assert late["verdict"] == "red" and late["since"]["pr"] == 313
        assert late["previous"]["pr"] == 312 and late["running"] == []

    def test_a_merge_after_the_instant_is_not_read(self, pm):
        """Dies to: a future merge counted in a replay."""
        checks = pm.transitions([_pr(312), _pr(313)], at="2026-10-18T13:10:00Z")
        assert 313 not in {c["owner"]["pr"] for c in checks.values() if c["owner"]}

    def test_a_run_that_started_after_the_instant_is_not_read(self, pm):
        """Dies to: a run started after the instant kept (a red the record did
        not yet hold at that time)."""
        a = copy.deepcopy(_pr(312))
        a["statusCheckRollup"].append(_row("late", "2026-10-18T13:30:00Z", "2026-10-18T13:40:00Z", "FAILURE"))
        checks = pm.transitions([a], at="2026-10-18T13:20:00Z")
        assert "late" not in checks or checks["late"]["owner"] is None
        assert pm.transitions([a])["late"]["verdict"] == "red"


class TestTheWords:
    def test_preflight_lines_keep_the_prefix_and_say_since_and_green_on(self, pm):
        """Dies to: the `red after merge: #N <check>` prefix the ship pins read
        changed, the since clause or the green-on clause dropped, or the macOS
        red given a false origin instead of the oldest-read clause."""
        lines = pm.lines(pm.transitions([_pr(312), _pr(313)]), oldest=312)
        assert lines[0] == ("red after merge: #313 portability (windows-latest) since 2026-10-18 13:26Z "
                            "(the leg finished 13:57Z), green on #312")
        assert lines[1] == "red after merge: #313 portability (macos-latest) since #312 or earlier (the oldest merge read)"
        assert len(lines) == 2

    def test_board_lines_name_each_red_with_its_merge_and_none_when_green(self, pm):
        """Dies to: a no-verdict run rendered green, or the all-green line missing."""
        checks = pm.transitions([_pr(312), _pr(313)])
        entries = pm.board_lines(checks, window=2, oldest=312)
        assert entries[0].startswith("portability (windows-latest): red since #313 (merged 2026-10-18 13:26Z, the leg finished 13:57Z), green on #312")
        green = copy.deepcopy(_pr(312))
        for leg in (WIN, MAC):
            _leg(green, leg)["conclusion"] = "SUCCESS"
        assert pm.board_lines(pm.transitions([green]), window=1, oldest=312) == ["none red among the last 1 merges"]

    def test_the_words_are_ascii_even_when_a_check_name_is_not(self, pm):
        a = copy.deepcopy(_pr(313))
        _leg(a, WIN)["name"] = "portabilit\u00e9 (windows)"
        for line in pm.lines(pm.transitions([a]), oldest=313):
            assert line.isascii()


class TestTheBannersVerdicts:
    def test_verdicts_follow_the_banners_ownership_newest_merge_first(self, pm):
        """The per-pull-request shape the Merged: line renders. Dies to: a
        leg still running on the newer merge silencing the older red, or a
        cancelled run read as a verdict."""
        a, b = _pr(312), _pr(313)
        out = pm.verdicts(pm.by_merge_desc([a, b]))
        assert out[313][0] == [WIN, MAC] or set(out[313][0]) == {WIN, MAC}
        assert 312 not in out   # its macOS red is owned by #313, its Windows green owns nothing red
        c = copy.deepcopy(b)
        c.update(number=320, mergedAt="2026-10-18T15:00:00Z")
        _leg(c, WIN).update(conclusion=None, status="IN_PROGRESS", completedAt=None)
        _leg(c, MAC).update(conclusion="CANCELLED")
        out = pm.verdicts(pm.by_merge_desc([a, b, c]))
        assert WIN in out[313][0] and out[320][1] == [f"{MAC} (cancelled)"]


class TestReadMerged:
    def test_read_merged_asks_gh_once_with_the_callers_author_and_drops_foreign_rows(self, pm):
        """Dies to: the author filter always or never passed, or a foreign row kept."""
        calls: list[list[str]] = []
        def gh(args):
            calls.append(list(args))
            return [{"number": 1, "mergedAt": "", "statusCheckRollup": []}, {"number": "x"}, "junk", None]
        rows = pm.read_merged(".", 7, gh=gh)
        assert [r["number"] for r in rows] == [1]
        assert calls == [["pr", "list", "--state", "merged", "--limit", "7", "--json", pm.MERGED_FIELDS]]
        pm.read_merged(".", 3, gh=gh, author="@me")
        assert calls[-1][:2] == ["pr", "list"] and "--author" in calls[-1] and "@me" in calls[-1]
        assert pm.read_merged(".", 3, gh=lambda args: None) == []

    def test_the_field_list_is_the_callers_and_defaults_to_the_rollup_fields(self, pm):
        """The Session Log debt readers (the board's records: line, the ship
        driver's row-debt read) ask for the lane's branch and merge stamp, not
        a hundred rollups, through the one merged read. Dies to: a second
        ``gh pr list --state merged`` spelled outside this module, or the lane
        fields missing the branch name."""
        calls: list[list[str]] = []
        def gh(args):
            calls.append(list(args))
            return [{"number": 9, "mergedAt": "2026-10-18T12:00:00Z", "headRefName": "lane/a"}]
        rows = pm.read_merged(".", 100, gh=gh, fields=pm.LANE_FIELDS)
        assert [r["headRefName"] for r in rows] == ["lane/a"]
        assert calls == [["pr", "list", "--state", "merged", "--limit", "100", "--json", pm.LANE_FIELDS]]
        # labels: the seat:<name> label the ship driver stamps names a lane no claim does (DEF-4044).
        assert set(pm.LANE_FIELDS.split(",")) == {"number", "mergedAt", "headRefName", "labels"}
        pm.read_merged(".", 2, gh=gh)
        assert calls[-1][-1] == pm.MERGED_FIELDS and "statusCheckRollup" in pm.MERGED_FIELDS


class TestTheRequiredRead:
    """The one ``gh pr checks <n> --required`` read the board's blocked row,
    the ship driver's ``status`` and the banner's ``Open PRs:`` line make
    (DEF-4063: the board alone made none, and printed one fixed phrase for
    every blocked pull request)."""

    def test_the_read_asks_once_and_splits_red_running_and_the_rest(self, pm):
        """Dies to: `cancel` read as anything but red (a job no runner picked
        up holds a merge as a failure does), `pending` as anything but
        running, or the caller's field list dropped (the driver adds `link`)."""
        calls: list[list[str]] = []
        answer = [{"name": "a", "bucket": "fail"}, {"name": "b", "bucket": "CANCEL"},
                  {"name": "c", "bucket": "pending"}, {"name": "d", "bucket": "pass"},
                  {"name": "e", "bucket": "skipping"}, "junk", None]

        def gh(args):
            calls.append(list(args))
            return answer

        reading = pm.read_required(27, gh)
        assert calls == [["pr", "checks", "27", "--required", "--json", pm.REQUIRED_FIELDS]]
        assert pm.REQUIRED_FIELDS == "name,bucket"
        assert [r["name"] for r in reading["red"]] == ["a", "b"]
        assert [r["name"] for r in reading["running"]] == ["c"]
        assert [r["name"] for r in reading["rows"]] == ["a", "b", "c", "d", "e"]
        pm.read_required("27", gh, fields="name,bucket,link")
        assert calls[-1][-1] == "name,bucket,link"

    def test_an_answer_that_is_not_a_list_is_unread_and_a_refusal_is_the_callers(self, pm):
        """A repository with no required checks answers rc=1 with no JSON:
        "could not read", never green. Dies to: None read as no red, or the
        caller's own refusal swallowed (the driver must say why)."""
        assert pm.read_required(1, lambda args: None) is None
        assert pm.read_required(1, lambda args: {"message": "Not Found"}) is None

        def refuse(args):
            raise RuntimeError("gh is offline")

        with pytest.raises(RuntimeError, match="offline"):
            pm.read_required(1, refuse)

    def test_held_by_names_the_red_else_the_running_else_a_review(self, pm):
        """The words of a blocked row: the banner's `waiting on N running`, at
        most three names then a count, ASCII. Dies to: a second phrase for
        the running case, a red outranked by a running sibling, or a non-ASCII
        check name reaching operator text."""
        assert pm.waiting_on(9) == "waiting on 9 running"
        assert pm.held_by(["guard"], ["x"]) == "required check red (guard)"
        assert pm.held_by(["a", "b", "c", "d", "e"], []) == "required checks red (a, b, c, and 2 more)"
        assert pm.held_by([], ["x", "y"]) == pm.waiting_on(2)
        assert pm.held_by([], []) == ("no required check is red or running, so a review or a required check "
                                      "that has not reported holds it")
        assert pm.held_by(["portabilité"], []).isascii()

    def test_the_banner_waits_in_the_same_words(self, pm):
        """The banner keeps its running tail literal so the row renders
        without this module; the board prints ``waiting_on``. Dies to: the
        two phrases drifting apart."""
        hook = _load(REPO_ROOT / "tools" / "cc" / "hooks" / "session_start.py", "session_start_words_under_test")
        row = {"number": 7, "headRefName": "lane/7", "baseRefName": "main", "mergeStateStatus": "BLOCKED",
               "autoMergeRequest": {"x": 1}, "statusCheckRollup": [
                   {"__typename": "CheckRun", "name": f"t{n}", "status": "IN_PROGRESS", "conclusion": None}
                   for n in range(3)]}
        assert hook._pr_summary(row, None).endswith(f"; auto-merge armed; {pm.waiting_on(3)}")

    def test_no_reader_spells_the_required_read_outside_this_module(self):
        """The three readers once each spelled their own `gh pr checks
        --required` argv, as a list or as call arguments. Dies to: a second
        one written beside a reader instead of a call to ``read_required``.
        An f-string telling the operator which command to run is words, not
        a read: its text is never the bare flag, and is not counted."""
        import ast

        spelled = sorted({
            path.relative_to(REPO_ROOT).as_posix()
            for path in (REPO_ROOT / "tools" / "cc").rglob("*.py")
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Constant) and node.value == "--required"
        })
        assert spelled == ["tools/cc/_post_merge.py"], spelled


def _run_row(status: str, conclusion: str | None, sha: str, run_id: int) -> dict:
    """One ``gh run list`` row as the board's base-run read asks for it."""
    return {"databaseId": run_id, "status": status, "conclusion": conclusion, "headSha": sha, "url": f"u-{run_id}"}


class TestTheBaseRunVerdict:
    """The base-run rule the board's ``checks:`` line reads the advisory
    Windows leg through (``post-merge-windows.yml`` on Espalier's own
    repository, the serial test files on windows-latest after each push to
    main): a push run attaches to the merge commit and appears in no pull
    request's rollup, so the merges' ownership rule above cannot see it.
    Frozen listings, newest first, as ``gh run list`` prints them."""

    def test_a_red_newest_is_red_since_itself_with_the_green_before_it(self, pm):
        """Dies to: the newest red not the verdict, or the green before it unread."""
        state = pm.base_run_verdict([_run_row("completed", "failure", "a" * 40, 3),
                                     _run_row("completed", "success", "b" * 40, 2)])
        assert state["verdict"] == "red" and state["sha"] == "a" * 40 and state["run"] == "3"
        assert state["since"] == {"sha": "a" * 40, "run": "3", "url": "u-3"}
        assert state["green_sha"] == "b" * 40 and not state["running"]

    def test_a_cancelled_newest_is_walked_past_to_the_older_red(self, pm):
        """Dies to: a cancelled run read as a verdict, green or red."""
        state = pm.base_run_verdict([_run_row("completed", "cancelled", "c" * 40, 4),
                                     _run_row("completed", "failure", "a" * 40, 3),
                                     _run_row("completed", "success", "b" * 40, 2)])
        assert state["verdict"] == "red" and state["run"] == "3" and state["no_verdict"] == ["cancelled"]

    def test_a_green_newest_is_green_and_the_walk_stops(self, pm):
        """Dies to: the walk going past a green to an older red."""
        state = pm.base_run_verdict([_run_row("completed", "success", "b" * 40, 5),
                                     _run_row("completed", "failure", "a" * 40, 3)])
        assert state["verdict"] == "green" and state["sha"] == "b" * 40 and state["since"] is None

    def test_a_streak_is_red_since_its_first_red_not_its_newest(self, pm):
        """Dies to: the since clause naming the newest red (the pack review's
        finding), the walk stopped by a run going or cancelled inside the
        streak, or the green before the streak unread."""
        state = pm.base_run_verdict([_run_row("completed", "timed_out", "d" * 40, 9),
                                     _run_row("in_progress", None, "e" * 40, 8),
                                     _run_row("completed", "cancelled", "c" * 40, 7),
                                     _run_row("completed", "failure", "a" * 40, 6),
                                     _run_row("completed", "success", "b" * 40, 5),
                                     _run_row("completed", "failure", "f" * 40, 4)])
        assert state["verdict"] == "red" and state["sha"] == "d" * 40 and state["run"] == "9"
        assert state["since"] == {"sha": "a" * 40, "run": "6", "url": "u-6"}
        assert state["green_sha"] == "b" * 40 and not state["running"] and state["no_verdict"] == []

    def test_no_green_in_the_listing_leaves_the_green_sha_empty(self, pm):
        state = pm.base_run_verdict([_run_row("completed", "failure", "a" * 40, 3),
                                     _run_row("completed", "startup_failure", "f" * 40, 1)])
        assert state["verdict"] == "red" and state["since"]["run"] == "1" and state["green_sha"] == ""

    def test_a_newer_run_going_is_running_beside_the_verdict(self, pm):
        """Dies to: a run still going read as a verdict, or not said."""
        state = pm.base_run_verdict([_run_row("queued", None, "e" * 40, 8),
                                     _run_row("completed", "success", "b" * 40, 5)])
        assert state["verdict"] == "green" and state["running"]

    def test_every_run_without_a_verdict_is_none_with_its_kinds(self, pm):
        state = pm.base_run_verdict([_run_row("completed", "cancelled", "c" * 40, 4),
                                     _run_row("completed", "skipped", "s" * 40, 3),
                                     _run_row("completed", "", "n" * 40, 2)])
        assert state["verdict"] == "none" and state["no_verdict"] == ["cancelled", "skipped", "no conclusion"]
        assert state["read"] == 3 and not state["running"]

    def test_an_empty_listing_a_non_list_and_a_foreign_row_read_as_no_runs(self, pm):
        """Dies to: a crash on a shape gh never promised."""
        assert pm.base_run_verdict([])["verdict"] == "none"
        assert pm.base_run_verdict({"total_count": 0})["verdict"] == "none"
        state = pm.base_run_verdict(["not a row", None, _run_row("completed", "success", "b" * 40, 5)])
        assert state["verdict"] == "green" and state["read"] == 1

    def test_the_red_set_is_the_three_conclusions_and_the_workflow_is_named_once(self, pm):
        """Dies to: the set widened (a cancelled run would read red) or narrowed
        (a timed-out run would read as no verdict); the board's `_RED` is
        pinned to this object in tests/test_board.py."""
        assert pm.RUN_RED == frozenset({"FAILURE", "TIMED_OUT", "STARTUP_FAILURE"})
        assert pm.WINDOWS_WORKFLOW == "post-merge-windows.yml"


class TestTheBaseRunWords:
    def test_a_red_names_the_first_red_the_newest_and_the_green_before(self, pm):
        """Dies to: the since clause naming the newest red, or the newest red
        and the green before the streak dropped."""
        state = pm.base_run_verdict([_run_row("completed", "timed_out", "d" * 40, 9),
                                     _run_row("completed", "failure", "a" * 40, 6),
                                     _run_row("completed", "success", "b" * 40, 5)])
        assert pm.base_run_lines(state) == [
            "post-merge-windows (main, advisory): red since aaaaaaa (run 6), still red on ddddddd (run 9), green on bbbbbbb"]

    def test_a_single_red_says_since_itself_and_a_newer_run_going(self, pm):
        state = pm.base_run_verdict([_run_row("in_progress", None, "e" * 40, 8),
                                     _run_row("completed", "failure", "a" * 40, 6),
                                     _run_row("completed", "success", "b" * 40, 5)])
        assert pm.base_run_lines(state, base="trunk") == [
            "post-merge-windows (trunk, advisory): red since aaaaaaa (run 6), green on bbbbbbb; a newer run is going"]

    def test_no_green_in_the_window_says_so(self, pm):
        state = pm.base_run_verdict([_run_row("completed", "failure", "a" * 40, 6)])
        assert pm.base_run_lines(state) == [
            "post-merge-windows (main, advisory): red since aaaaaaa (run 6) (no green among the runs read)"]

    def test_green_absent_empty_going_and_no_state_render_nothing(self, pm):
        """Dies to: a line for a leg that is not red (the deployed board runs
        on trees without the workflow, and here before its first run)."""
        assert pm.base_run_lines(pm.base_run_verdict([_run_row("completed", "success", "b" * 40, 5)])) == []
        assert pm.base_run_lines({"verdict": "absent"}) == []
        assert pm.base_run_lines(pm.base_run_verdict([])) == []
        assert pm.base_run_lines(pm.base_run_verdict([_run_row("queued", None, "e" * 40, 8)])) == []
        assert pm.base_run_lines(None) == []

    def test_no_verdict_and_unread_are_each_one_line(self, pm):
        state = pm.base_run_verdict([_run_row("completed", "cancelled", "c" * 40, 4)])
        assert pm.base_run_lines(state) == ["post-merge-windows (main, advisory): no verdict on every run read (cancelled; 1 run)"]
        two = pm.base_run_verdict([_run_row("completed", "cancelled", "c" * 40, 4), _run_row("completed", "stale", "s" * 40, 3)])
        assert pm.base_run_lines(two) == ["post-merge-windows (main, advisory): no verdict on every run read (cancelled, stale; 2 runs)"]
        assert pm.base_run_lines({"unread": "gh run list answered rc=1 with no JSON"}) == [
            "post-merge-windows (main, advisory): unread (gh run list answered rc=1 with no JSON)"]

    def test_board_lines_keep_the_none_line_off_only_when_the_leg_is_red(self, pm):
        """Dies to: `none red among the last N merges` printed above a red leg,
        or dropped above an unread or silent one, or the leg's line printed
        before the pull-request legs."""
        green = copy.deepcopy(_pr(312))
        for leg in (WIN, MAC):
            _leg(green, leg)["conclusion"] = "SUCCESS"
        checks = pm.transitions([green])
        red = pm.base_run_verdict([_run_row("completed", "failure", "a" * 40, 6)])
        assert pm.board_lines(checks, window=1, oldest=312, base_run=red) == [
            "post-merge-windows (main, advisory): red since aaaaaaa (run 6) (no green among the runs read)"]
        assert pm.board_lines(checks, window=1, oldest=312, base_run={"unread": "x"}) == [
            "none red among the last 1 merges", "post-merge-windows (main, advisory): unread (x)"]
        assert pm.board_lines(checks, window=1, oldest=312, base_run={"verdict": "absent"}) == [
            "none red among the last 1 merges"]
        assert pm.board_lines(checks, window=1, oldest=312) == ["none red among the last 1 merges"]
        both = pm.board_lines(pm.transitions([_pr(312), _pr(313)]), window=2, oldest=312, base_run=red)
        assert len(both) == 3 and both[0].startswith("portability (windows-latest)")
        assert both[-1].startswith("post-merge-windows (main, advisory): red since")

    def test_newer_runs_without_a_verdict_above_a_green_are_named_never_hidden(self, pm):
        """Dies to: a cancelled newest run walked past to an older green with
        nothing printed (a hang the job's bound cuts may conclude cancelled on
        every push, and one old green would hide them all), or a run going
        dropped from the all-no-verdict line."""
        state = pm.base_run_verdict([_run_row("completed", "cancelled", "c" * 40, 7),
                                     _run_row("completed", "cancelled", "d" * 40, 6),
                                     _run_row("completed", "success", "b" * 40, 5)])
        assert pm.base_run_lines(state) == [
            "post-merge-windows (main, advisory): no verdict on the newest 2 runs (cancelled), green on bbbbbbb before them"]
        one = pm.base_run_verdict([_run_row("in_progress", None, "e" * 40, 8), _run_row("completed", "stale", "c" * 40, 7),
                                   _run_row("completed", "success", "b" * 40, 5)])
        assert pm.base_run_lines(one) == [
            "post-merge-windows (main, advisory): no verdict on the newest 1 run (stale), green on bbbbbbb before it; "
            "a newer run is going"]
        none = pm.base_run_verdict([_run_row("queued", None, "e" * 40, 8), _run_row("completed", "cancelled", "c" * 40, 4)])
        assert pm.base_run_lines(none) == [
            "post-merge-windows (main, advisory): no verdict on every run read (cancelled; 1 run); a run is going"]

    def test_the_base_run_words_are_ascii(self, pm):
        assert all(line.isascii() for line in pm.base_run_lines({"unread": "café"}))
