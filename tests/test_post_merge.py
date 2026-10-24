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
        assert set(pm.LANE_FIELDS.split(",")) == {"number", "mergedAt", "headRefName"}
        pm.read_merged(".", 2, gh=gh)
        assert calls[-1][-1] == pm.MERGED_FIELDS and "statusCheckRollup" in pm.MERGED_FIELDS
