"""The subject that names a lane in tools/cc/ship.py: the pull request's
default title (``_title_refusal``), the branch ``lane`` makes, and the lane
``preflight`` forecasts on the default branch. Each reads the lane's own
newest commit -- never a merge of the base, nor a commit touching nothing
outside the record folders, the commits that sit at HEAD in the usual flows
(a base merged in before the first push or by a catch-up; the handoff's row,
a fold, a ledger strike) -- a records-only lane's newest commit outside the
Session Log, else its newest non-merge commit, and HEAD's own subject where
the lane holds none.

Real git in tmp_path: which commit is the lane's own newest is git's answer
(the first-parent walk, the merge filter, the pathspec that leaves the rows
out), so no stand-in runner can be the oracle for it. The rows of
tests/test_ship_driver.py answer the same read from a table and pin the
verbs' order around it.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHIP = ROOT / "tools" / "cc" / "ship.py"

LANE_CHANGE = "fix(x): the lane's own change"
ROW = "docs(memory): t's row: the lane hands off"
BASE_CHANGE = "feat: a change on the base"
ROW_FILE = "memory/session-log.d/2026-01-01-000000-t.md"


def _load():
    spec = importlib.util.spec_from_file_location("_ship_lane_subject", SHIP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_ship_lane_subject"] = mod  # registered before exec (3.14)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ship(monkeypatch):
    mod = _load()
    # The lane verb's two reads that are not git: the default branch (gh) and
    # whether another session works in this checkout (the session registry).
    mod.default_branch = lambda: "main"
    mod._refuse_a_shared_checkout = lambda root: None
    yield mod
    sys.modules.pop("_ship_lane_subject", None)


class _Repo:
    """A scratch repository on ``main`` whose commits are stamped one second
    apart in the order made, so a date-ordered walk and a first-parent walk
    disagree wherever a test makes them."""

    def __init__(self, path: Path):
        self.path = path
        self._tick = 0
        path.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@t.com")
        self.git("config", "user.name", "T")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *argv: str) -> str:
        self._tick += 1
        stamp = f"2026-01-01T00:{self._tick // 60:02d}:{self._tick % 60:02d}Z"
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
        return subprocess.run(["git", *argv], cwd=self.path, env=env, check=True, capture_output=True,
                              text=True, encoding="utf-8").stdout.strip()

    def commit(self, subject: str, *paths: str) -> None:
        assert paths, "name the files the commit touches: whether it is a row alone is the question"
        for rel in paths:
            target = self.path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"{subject}\n{self._tick}\n", encoding="utf-8")
            self.git("add", rel)
        self.git("commit", "-q", "-m", subject)

    def origin_main_at(self, rev: str) -> None:
        self.git("update-ref", "refs/remotes/origin/main", rev)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    made = _Repo(tmp_path / "r")
    made.commit("chore: the first commit", "a.txt")
    monkeypatch.chdir(made.path)   # repo_root() reads the working directory
    return made


def _title(ship, repo: _Repo, *, given: str | None = None) -> str:
    state = ship.PrePushState(repo.path, "main", repo.git("branch", "--show-current"), title=given)
    assert ship._title_refusal(state) is None
    return state.title


class TestTheTitleIsTheLanesOwnSubject:
    def test_a_merge_of_the_base_at_head_titles_by_the_lane_commit_beneath_it(self, ship, repo):
        """The base merged in before the first push: the merge's subject
        titled the pull request, and the marker was bound to it."""
        repo.git("switch", "-q", "-c", "lane/x")
        repo.commit(LANE_CHANGE, "x.py")
        repo.git("switch", "-q", "main")
        repo.commit(BASE_CHANGE, "base.py")
        repo.origin_main_at("main")
        repo.git("switch", "-q", "lane/x")
        repo.git("merge", "-q", "--no-edit", "main")
        assert repo.git("log", "-1", "--format=%s").startswith("Merge branch")
        assert _title(ship, repo) == LANE_CHANGE

    def test_the_handoffs_row_at_head_titles_by_the_lane_commit_beneath_it(self, ship, repo):
        """/handoff commits the Session Log row on the lane before its push,
        so the row was HEAD when `open` read the title."""
        repo.origin_main_at("main")
        repo.git("switch", "-q", "-c", "lane/x")
        repo.commit(LANE_CHANGE, "x.py")
        repo.commit(ROW, ROW_FILE)
        assert _title(ship, repo) == LANE_CHANGE

    def test_rows_and_a_merge_above_the_change_are_both_passed_over(self, ship, repo):
        repo.git("switch", "-q", "-c", "lane/x")
        repo.commit(LANE_CHANGE, "x.py")
        repo.git("switch", "-q", "main")
        repo.commit(BASE_CHANGE, "base.py")
        repo.origin_main_at("main")
        repo.git("switch", "-q", "lane/x")
        repo.git("merge", "-q", "--no-edit", "main")
        repo.commit(ROW, ROW_FILE)
        repo.commit("chore(records): fold 1 parked Session Log row", "memory/session-log.d/2026-01-01-000001-u.md")
        assert _title(ship, repo) == LANE_CHANGE

    def test_a_prune_of_the_session_log_above_the_change_is_passed_over(self, ship, repo):
        """The driver's prune deletes rows past the cap: a commit touching the
        Session Log alone, by deletion."""
        repo.commit("docs(memory): an older row", "memory/session-log.d/2025-12-31-000000-w.md")
        repo.origin_main_at("main")
        repo.git("switch", "-q", "-c", "lane/x")
        repo.commit(LANE_CHANGE, "x.py")
        repo.git("rm", "-q", "memory/session-log.d/2025-12-31-000000-w.md")
        repo.git("commit", "-q", "-m", "chore(records): prune the Session Log to its cap of 1")
        assert _title(ship, repo) == LANE_CHANGE

    def test_a_stale_base_ref_never_lets_a_commit_the_merge_brought_in_title_the_lane(self, ship, repo):
        """The title is read before `open` fetches the base. With
        origin/main behind the base the lane merged, the base's commit --
        newer than the lane's by date -- is in the range; the first-parent
        walk never reaches it."""
        repo.origin_main_at("main")   # stale from here on
        repo.git("switch", "-q", "-c", "lane/x")
        repo.commit(LANE_CHANGE, "x.py")
        repo.git("switch", "-q", "main")
        repo.commit(BASE_CHANGE, "base.py")
        repo.git("switch", "-q", "lane/x")
        repo.git("merge", "-q", "--no-edit", "main")
        assert _title(ship, repo) == LANE_CHANGE

    def test_rows_alone_under_a_merge_with_a_stale_base_ref_never_reach_the_base(self, ship, repo):
        """The merge equals the base's side once the rows are left out, the
        shape where history simplification would follow the second parent
        onto the base's own commit; the lane holds records alone, so its
        newest non-merge commit names it, never the merge or the base."""
        repo.origin_main_at("main")   # stale from here on
        repo.git("switch", "-q", "-c", "lane/x")
        repo.commit(ROW, ROW_FILE)
        repo.git("switch", "-q", "main")
        repo.commit(BASE_CHANGE, "base.py")
        repo.git("switch", "-q", "lane/x")
        repo.git("merge", "-q", "--no-edit", "main")
        assert _title(ship, repo) == ROW

    def test_a_ledger_strike_above_the_change_is_passed_over(self, ship, repo):
        """The lane strikes its ledger row before the handoff: a commit
        touching the ledger and probe folders alone."""
        repo.origin_main_at("main")
        repo.git("switch", "-q", "-c", "lane/x")
        repo.commit(LANE_CHANGE, "x.py")
        repo.commit("docs(ledger): strike the row", "task-packs/ledger.d/X-1.md", "task-packs/probes.d/X-1.json")
        repo.commit(ROW, ROW_FILE)
        assert _title(ship, repo) == LANE_CHANGE

    def test_a_filing_lane_is_titled_by_its_filing_not_its_row(self, ship, repo):
        repo.origin_main_at("main")
        repo.git("switch", "-q", "-c", "lane/x")
        repo.commit("docs(ledger): file two rows", "task-packs/ledger.d/X-2.md", "task-packs/probes.d/X-2.json")
        repo.commit(ROW, ROW_FILE)
        assert _title(ship, repo) == "docs(ledger): file two rows"

    def test_a_root_below_the_top_reads_the_same_subject(self, ship, repo):
        """The pathspecs are anchored at the top, so a caller passing a
        folder inside the checkout gets the lane's answer, not HEAD's."""
        repo.origin_main_at("main")
        repo.git("switch", "-q", "-c", "lane/x")
        repo.commit(LANE_CHANGE, "x.py")
        repo.commit(ROW, ROW_FILE)
        assert ship.lane_subject(repo.path / "memory", "main") == LANE_CHANGE

    def test_a_commit_carrying_a_row_beside_code_is_the_lanes_own(self, ship, repo):
        """Only a commit that touches the Session Log alone is passed over."""
        repo.origin_main_at("main")
        repo.git("switch", "-q", "-c", "lane/x")
        repo.commit("fix(x): an earlier step", "x.py")
        repo.commit(LANE_CHANGE, "y.py", ROW_FILE)
        assert _title(ship, repo) == LANE_CHANGE

    def test_a_lane_of_rows_alone_is_titled_by_its_head(self, ship, repo):
        repo.origin_main_at("main")
        repo.git("switch", "-q", "-c", "lane/x")
        repo.commit("docs(memory): an older row", "memory/session-log.d/2026-01-01-000002-v.md")
        repo.commit(ROW, ROW_FILE)
        assert _title(ship, repo) == ROW

    def test_with_no_base_ref_the_title_is_heads_subject(self, ship, repo):
        repo.git("switch", "-q", "-c", "lane/x")
        repo.commit(LANE_CHANGE, "x.py")
        repo.commit(ROW, ROW_FILE)
        assert _title(ship, repo) == ROW

    def test_an_explicit_title_is_taken_as_given(self, ship, repo):
        repo.origin_main_at("main")
        repo.git("switch", "-q", "-c", "lane/x")
        repo.commit(LANE_CHANGE, "x.py")
        repo.commit(ROW, ROW_FILE)
        assert _title(ship, repo, given="feat: typed by hand") == "feat: typed by hand"


class TestTheLaneIsNamedFromTheSameSubject:
    """``lane`` on the default branch, and the lane ``preflight`` forecasts
    there, slug the subject the title reads: the handoff's on-base path runs
    ``lane`` with the row at HEAD."""

    @staticmethod
    def _fix_then_row_on_main(repo: _Repo) -> None:
        repo.origin_main_at("main")
        repo.commit(LANE_CHANGE, "x.py")
        repo.commit(ROW, ROW_FILE)

    def test_lane_names_the_branch_from_the_change_under_the_row(self, ship, repo, capsys):
        self._fix_then_row_on_main(repo)
        assert ship.lane() == 0
        assert repo.git("branch", "--show-current") == "lane/fix-x-the-lane-s-own-change"
        assert repo.git("rev-parse", "main") == repo.git("rev-parse", "origin/main")
        assert "moved the unmerged commits to lane/fix-x-the-lane-s-own-change" in capsys.readouterr().out

    def test_preflight_forecasts_the_lane_lane_will_make(self, ship, repo, capsys):
        self._fix_then_row_on_main(repo)
        ship.PRE_PUSH_CHECKS = ()   # the forecast's own checks read gh; the lane's name is the row here
        ship._seat_notes = lambda state: None
        ship._forecast_pre_push(repo.path, "main", "main")
        assert "moves the commits to lane/fix-x-the-lane-s-own-change first" in capsys.readouterr().out
