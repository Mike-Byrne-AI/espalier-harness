"""The merge-cost census: catch-ups per merged pull request, catch-up merges
replayed as GitHub merges them, and the record files' conflict blocks classed.

Every git and gh call goes through an injected runner, so these rows drive the
parsing and the aggregation without a repository or the network. What a real
replay measured is recorded in the script's docstring (the changelog's 0
conflicts with the union driver on, 10 of 30 with it off, 2026-10-09).
"""
# pytest-marker: default-unit  (pure functions over an injected runner; no subprocess)
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import merge_cost_census as mcc  # noqa: E402


def _done(stdout: str = "", rc: int = 0, stderr: str = "") -> tuple[int, str, str]:
    """What ``tools/cc/ship.py::run`` returns: ``(returncode, stdout, stderr)``."""
    return rc, stdout, stderr


def _pr(number: int, *headlines: str, head: str = "lane/x") -> dict:
    return {"number": number, "headRefName": head,
            "commits": [{"oid": f"{number}{i:02d}", "messageHeadline": h}
                        for i, h in enumerate(headlines)]}


class TestCatchUpsAreTheBaseMergedIn:
    def test_both_spellings_count_and_nothing_else_does(self):
        pr = _pr(1, "fix(x): a change", "Merge branch 'main' into lane/x",
                 "Merge remote-tracking branch 'origin/main' into lane/x",
                 "Merge pull request #7 from lane/y", "Merge branch 'lane/y' into lane/x")
        assert mcc.catch_up_commits(pr) == ["101", "102"]

    def test_rows_count_runs_attempts_and_failures(self):
        runs = [{"conclusion": "success", "attempt": 1}, {"conclusion": "failure", "attempt": 2}]

        def runner(cmd, cwd=None):
            assert cmd[:3] == ["gh", "run", "list"] and "lane/x" in cmd
            return _done(json.dumps(runs))

        rows = mcc.catch_up_rows([_pr(5, "Merge branch 'main' into lane/x")], runner)
        assert rows == [{"pr": 5, "catch_ups": 1, "test_runs": 2, "attempts": 3, "failed_runs": 1}]


class TestTheReplayIsGitHubsMerge:
    def test_every_merge_driver_becomes_a_text_merge(self):
        attrs = ("# comment\n*.py text eol=lf\nCHANGELOG.md text eol=lf merge=union\n"
                 "docs/x.md merge=ours\n*.png binary\n")
        assert mcc.driver_overrides(attrs) == ["CHANGELOG.md merge=text", "docs/x.md merge=text"]

    def test_the_overrides_land_in_the_clones_own_info_attributes(self, tmp_path):
        """The override must reach the replay's clone, or the changelog's union
        driver hides its conflicts (0 of 30 with it on, 10 with it off)."""
        (tmp_path / ".gitattributes").write_text("CHANGELOG.md merge=union\n", encoding="utf-8")
        seen: list[list[str]] = []

        def runner(cmd, cwd=None):
            seen.append(cmd)
            return _done()

        clone = mcc.scratch_clone(tmp_path, runner)
        try:
            assert seen[0][:2] == ["git", "clone"] and "--shared" in seen[0]
            assert (clone / ".git" / "info" / "attributes").read_text(encoding="utf-8") == (
                "CHANGELOG.md merge=text\n"
            )
            assert tmp_path not in clone.parents, "the override must never touch the source repo"
        finally:
            import shutil
            shutil.rmtree(clone.parent, ignore_errors=True)

    def _runner(self, merge_tree: tuple[int, str, str], cat_file: str = ""):
        def runner(cmd, cwd=None):
            if "rev-parse" in cmd:
                return _done(cmd[-1].replace("^", "p") + "\n")
            if "merge-tree" in cmd:
                return merge_tree
            if "cat-file" in cmd:
                return _done(cat_file)
            raise AssertionError(cmd)
        return runner

    def test_a_clean_replay_and_a_conflicted_one(self, tmp_path):
        clean = self._runner(_done("tree0\n"))
        assert mcc.replay(tmp_path, "abc", clean) == (None, [])
        conflicted = self._runner(_done("tree1\nCHANGELOG.md\ntask-packs/FORWARD_LEDGER.md\n", rc=1))
        assert mcc.replay(tmp_path, "abc", conflicted) == (
            "tree1", ["CHANGELOG.md", "task-packs/FORWARD_LEDGER.md"])

    def test_a_merge_tree_error_never_reads_clean(self, tmp_path):
        with pytest.raises(SystemExit):
            mcc.replay(tmp_path, "abc", self._runner(_done(rc=128, stderr="fatal")))

    def test_a_parent_the_clone_lacks_never_reads_clean(self, tmp_path):
        with pytest.raises(SystemExit):
            mcc.replay(tmp_path, "abc", lambda cmd, cwd=None: _done(rc=128))


class TestBlocksAreClassedByWhatTheySpan:
    @pytest.mark.parametrize("lines, kind", [
        (["**Live: 312** — 1 logic bugs"], "ledger: derived counts"),
        (["| [§C0](#c0) | Standalone | 221 (**156 live**, 65 closed) | MIXED |"], "ledger: derived counts"),
        (["## §2 — Open fixes, by unit of work (310 LIVE issues in 43 classes)"], "ledger: derived counts"),
        (["| `DEF-1` | §C0 | a.py |"], "ledger: id index rows"),
        (["| `DEF-1` | a.py | what | nit | LOGIC_BUG | MAINTAINER |"], "ledger: member rows"),
        (["some prose line"], "ledger: other"),
    ])
    def test_ledger_blocks(self, lines, kind):
        assert mcc.classify_block(mcc.LEDGER, lines) == kind

    def test_probes_blocks(self):
        assert mcc.classify_block(mcc.PROBES, [' "_count": 322,']) == "probes: _count"
        assert mcc.classify_block(mcc.PROBES, ['   "id": "DEF-1",']) == "probes: entries"

    def test_conflict_blocks_take_both_sides_and_nothing_outside(self):
        text = ("keep\n<<<<<<< ours\na\n=======\nb\n>>>>>>> theirs\nkeep\n"
                "<<<<<<< ours\nc\n=======\n>>>>>>> theirs\n")
        assert mcc.conflict_blocks(text) == [["a", "b"], ["c"]]


def test_replay_all_aggregates_files_and_blocks(tmp_path):
    ledger_body = "x\n<<<<<<< a\n**Live: 2**\n=======\n**Live: 3**\n>>>>>>> b\n"

    def runner(cmd, cwd=None):
        if "rev-parse" in cmd:
            return _done("p\n")
        if "merge-tree" in cmd:
            return _done("t1\ntask-packs/FORWARD_LEDGER.md\n", rc=1)
        if "cat-file" in cmd:
            return _done(ledger_body)
        raise AssertionError(cmd)

    prs = [_pr(1, "Merge branch 'main' into lane/x"), _pr(2, "unrelated")]
    out = mcc.replay_all(prs, tmp_path, runner)
    assert out["catch_up_merges"] == 1 and out["conflicted"] == 1 and out["record_files_only"] == 1
    assert out["files"] == {"task-packs/FORWARD_LEDGER.md": 1}
    assert out["blocks"] == {"ledger: derived counts": 1}


def test_main_reads_a_saved_window_and_rejects_an_unknown_report(tmp_path, capsys):
    prs_file = tmp_path / "prs.json"
    prs_file.write_text(json.dumps([_pr(3, "Merge branch 'main' into lane/x")]), encoding="utf-8")

    def runner(cmd, cwd=None):
        if cmd[:3] == ["gh", "run", "list"]:
            return _done(json.dumps([{"conclusion": "success", "attempt": 1}] * 2))
        raise AssertionError(f"no gh pr list with --prs-json: {cmd}")

    assert mcc.main(["--prs-json", str(prs_file), "catch-ups"], runner) == 0
    assert "1 merged; 1 with a catch-up; 1 catch-ups; 2 test runs (2.00 per pull request)" in (
        capsys.readouterr().out)
    with pytest.raises(SystemExit):
        mcc.main(["--prs-json", str(prs_file), "nonsense"], runner)


class TestStaleIsTheBoardsReadOnTheMergeParents:
    """The stale report replays ``_merge_rules.stale_base`` (pinned against
    real git in tests/test_stale_base.py) on each merge commit's parents: the
    first is the base the pull request landed on, the second its head."""

    BASE, HEAD = "b" * 40, "h" * 40

    def _runner(self, merges: dict[str, str]):
        def runner(cmd, cwd=None):
            if cmd[:3] == ["git", "rev-list", "--parents"]:
                parents = merges.get(cmd[-1])
                return _done(f"{cmd[-1]} {parents}\n") if parents else _done("", rc=128)
            if cmd[:3] == ["gh", "run", "list"]:
                return _done(json.dumps([{"workflowName": "CI", "createdAt": "T", "headSha": self.HEAD}]))
            if cmd[:2] == ["git", "diff"]:
                assert cmd[-1] == f"{self.BASE}...{self.HEAD}"
                return _done("tools/cc/a.py\n")
            raise AssertionError(f"unplanned: {cmd}")
        return runner

    def _rules(self, seen: list, result: dict):
        import types

        def stale_base(root, **kw):
            seen.append(kw)
            return result
        return types.SimpleNamespace(tested_at=lambda runs, head: "T" if head == self.HEAD else "", stale_base=stale_base)

    def test_the_read_gets_the_first_parent_as_base_and_the_second_as_head(self):
        """Dies to: the parents swapped (the head read as the base)."""
        seen: list = []
        prs = [{"number": 9, "headRefName": "lane/x", "mergeCommit": {"oid": "m9"}}]
        near = {"moved": 2, "near": ["tools/cc/a.py (both changed)"], "unread": ""}
        rows = mcc.stale_rows(prs, self._runner({"m9": f"{self.BASE} {self.HEAD}"}), rules=self._rules(seen, near))
        assert rows == [{"pr": 9, "moved": 2, "near": ["tools/cc/a.py (both changed)"], "unread": ""}]
        assert seen[0]["base_ref"] == self.BASE[:12] and seen[0]["pr_rev"] == self.HEAD
        assert seen[0]["tested_when"] == "T" and seen[0]["pr_paths"] == ["tools/cc/a.py"]

    def test_a_merge_it_cannot_read_is_unread_never_fresh(self):
        seen: list = []
        prs = [{"number": 1, "headRefName": "a"}, {"number": 2, "headRefName": "b", "mergeCommit": {"oid": "gone"}},
               {"number": 3, "headRefName": "c", "mergeCommit": {"oid": "squash"}}]
        rows = mcc.stale_rows(prs, self._runner({"squash": self.BASE}), rules=self._rules(seen, {}))
        assert [r["unread"] for r in rows] == ["no merge commit listed", "gone is not here (fetch)",
                                               "squash is not a two-parent merge"]
        assert seen == []

    def test_the_summary_counts_the_read_ones_and_says_when_to_re_raise(self):
        rows = [{"pr": 1, "moved": 1, "near": ["a.py (both changed)"], "unread": ""},
                {"pr": 2, "moved": 1, "near": [], "unread": ""},
                {"pr": 3, "moved": 0, "near": [], "unread": "no merge commit listed"}]
        text = mcc.render(["stale"], None, None, rows)
        assert "3 merged, 2 read: the base moved after the last CI run on 2, near the files on 1" in text
        assert "re-raise" not in text
        rows[1]["near"] = ["b.py (both changed)"]
        assert "more than half are near, so re-raise the rule" in mcc.render(["stale"], None, None, rows)
