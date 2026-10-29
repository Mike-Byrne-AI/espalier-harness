"""`scripts/red_after_merge_census.py`, the instrument behind the post-merge
verdict module. This file pins that the census keeps no copy of the rule (the
module is loaded by path), because a copy beside the module is two homes that
drift the moment one is edited; and it guards the replay and the classifier: it
replays the frozen #312/#313 rollups at the two instants the roadmap names, and
its classifier buckets a failing node id by the ledger rows that name its file.
Each test names the mutation it dies to."""
from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT = REPO_ROOT / "scripts" / "red_after_merge_census.py"
_MODULE = REPO_ROOT / "tools" / "cc" / "_post_merge.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "post_merge"
WIN = "portability (windows-latest)"


def _load():
    spec = importlib.util.spec_from_file_location("red_after_merge_census", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def census():
    return _load()


def _rows() -> list[dict]:
    return [json.loads((FIXTURES / f"pr{n}.json").read_text(encoding="utf-8")) for n in (313, 312)]


class TestTheCensusKeepsNoCopy:
    def test_the_rule_is_the_modules_and_no_definition_of_it_is_here(self, census):
        """Dies to: a copy of the ownership or transition rule kept in the
        script beside the module (two homes for one rule)."""
        assert pathlib.Path(census._pm.__file__).resolve() == _MODULE.resolve()
        defined = {n.name for n in ast.walk(ast.parse(_SCRIPT.read_text(encoding="utf-8")))
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        moved = {"check_outcome", "latest_run_per_check", "verdicts", "transitions", "replay", "lines", "board_lines"}
        assert not (defined & moved), sorted(defined & moved)


class TestTheReplay:
    def test_at_14_15_the_windows_leg_is_red_since_313_and_green_on_312(self, census, monkeypatch, capsys):
        """The roadmap's oracle. Dies to: --at not handed to the module, or the
        listing read from the wrong instant."""
        monkeypatch.setattr(census, "gh_json", lambda args, repo=None: _rows() if args[:2] == ["pr", "list"] else None)
        assert census.main(["--since", "2026-10-18", "--at", "2026-10-18T14:15:00Z"]) == 0
        out = capsys.readouterr().out
        assert "replayed at 2026-10-18T14:15:00Z" in out
        assert f"{WIN}: red since #313 (merged 2026-10-18 13:26Z, the leg finished 13:57Z), green on #312" in out

    def test_at_14_00_the_312_leg_is_still_running(self, census, monkeypatch, capsys):
        """Dies to: a run that finished after the instant read as its verdict."""
        monkeypatch.setattr(census, "gh_json", lambda args, repo=None: _rows() if args[:2] == ["pr", "list"] else None)
        assert census.main(["--at", "2026-10-18T14:00:00Z", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        win = data["checks"][WIN]
        assert win["verdict"] == "red" and win["since"]["pr"] == 313 and win["previous"] is None
        assert win["running"] == [312]

    def test_since_cuts_older_merges_and_an_empty_read_is_a_loud_exit(self, census, monkeypatch, capsys):
        """Dies to: --since ignored, or an empty listing rendered as all green."""
        monkeypatch.setattr(census, "gh_json", lambda args, repo=None: _rows() if args[:2] == ["pr", "list"] else None)
        assert census.main(["--since", "2026-10-18T13:10:00Z"]) == 0
        assert "merged pull requests read: 1 (#313 oldest merge to #313)" in capsys.readouterr().out
        monkeypatch.setattr(census, "gh_json", lambda args, repo=None: None)
        assert census.main([]) == 2


class TestTheClassifier:
    def test_run_and_job_come_from_the_details_url(self, census):
        row = {"detailsUrl": "https://github.com/o/r/actions/runs/39169603099/job/117799717558"}
        assert census.run_and_job(row) == ("39169603099", "117799717558")
        assert census.run_and_job({"detailsUrl": "https://example/x"}) is None

    def test_failing_node_ids_are_read_once_each_from_failed_and_error_lines(self, census):
        """Dies to: an ERROR-at-setup id missed, or a repeated id counted twice."""
        log = ("x\tstep\t2026Z FAILED tests/test_a.py::TestA::test_one - AssertionError\n"
               "x\tstep\t2026Z _ ERROR at setup of TestB.test_two _\n"
               "x\tstep\t2026Z ERROR tests/test_b.py::TestB::test_two\n"
               "x\tstep\t2026Z FAILED tests/test_a.py::TestA::test_one - again\n")
        assert census.failing_node_ids(log) == ["tests/test_a.py::TestA::test_one", "tests/test_b.py::TestB::test_two"]

    def test_a_leg_is_known_only_when_every_failing_file_has_a_ledger_row(self, census):
        """Dies to: the bucket keyed on the node id instead of its file, a leg
        with one unnamed file read as known, or an unreadable log counted."""
        merged = _rows()
        known = {"tests/test_xdist_never_ran.py": ["DEF-2025"]}
        logs = {
            ("39169603099", "117799717558"): "FAILED tests/test_xdist_never_ran.py::T::test_a\n",
            ("39165778649", "117788310512"): ("FAILED tests/test_xdist_never_ran.py::T::test_a\n"
                                               "FAILED tests/test_other.py::T::test_b\n"),
        }
        for pr, (run, job) in zip(merged, logs):
            for row in pr["statusCheckRollup"]:
                if row.get("name") == WIN or row.get("name") == "portability (macos-latest)":
                    row["detailsUrl"] = f"https://github.com/o/r/actions/runs/{run}/job/{job}"
        result = census.classify(merged, repo=None, max_logs=10, read_log=lambda run, job: logs.get((run, job), ""), known=known)
        verdicts = {(leg["pr"], leg["check"]): leg["verdict"] for leg in result["legs"]}
        assert verdicts[(313, WIN)] == "known"
        assert verdicts[(312, "portability (macos-latest)")] == "unclassified"
        assert result["read"] == 3 and result["known"] == 2 and result["known_share"] == pytest.approx(2 / 3)
        capped = census.classify(merged, repo=None, max_logs=0, read_log=lambda run, job: "x", known=known)
        assert all(leg["verdict"] == "unread" for leg in capped["legs"]) and capped["known_share"] is None
