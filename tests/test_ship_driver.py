"""Unit contracts for tools/cc/ship.py -- the driver behind /ship.

These rows pin the driver's order and refusals because a pushed lane cannot
be un-pushed: a verb that mutates the remote in the wrong state, or before a
check it promised, is a stall or a loss the command exists to prevent.
Every verb in that script derives what it needs from git and gh and refuses,
by name, the state it must not act on. These rows drive the verbs in-process
with a recording stand-in for the script's single spawn point, so each refusal
is pinned twice: as the message the operator reads, and as a NON-event -- a
refused verb pushes nothing, opens nothing, edits no title, tags nothing.

The script is loaded by path and registered before exec: tools/cc/ runs
standalone with zero espalier imports, so a plain import would drag the engine
into that graph, and a path-loaded module needs the registration on 3.14.
"""
# pytest-marker: default-unit  (in-process calls into a path-loaded script through
# its injectable runner: no subprocess, no git, no live-tree read)
from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

from espalier._safe_walk import visible
from tests._live_tree import checkout_glob
from _wired_settings import write_wired_settings

ROOT = Path(__file__).resolve().parent.parent
SHIP = ROOT / "tools" / "cc" / "ship.py"

MARKER = "HARNESS-UPDATE-APPROVED"
#: Two distinct 40-hex heads: the lane's, and one the lane has moved past.
HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
OLD_HEAD = "0f1e2d3c4b5a69788796a5b4c3d2e1f098765432"
SHORT = HEAD[:7]

#: A guard the fake repo root can carry: the smallest predicate that answers
#: the question `open` asks it (does this diff path need the marker).
_GUARD_SOURCE = 'def is_protected(rel_path):\n    return rel_path.startswith("tools/cc/")\n'


def _load():
    spec = importlib.util.spec_from_file_location("_ship_driver", SHIP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_ship_driver"] = mod  # registered before exec (3.14)
    spec.loader.exec_module(mod)
    return mod


def _oracle(rows: list[dict] | None, *, oracle: str = "registry", note: str = "", caller: dict | None = None):
    """A stand-in for checkout_sync's occupancy oracle: ``rows`` are the
    sessions it places in the checkout (None: it cannot tell), each from the
    registry unless ``oracle`` says markers; ``caller`` is the asking
    session's own entry, wherever it is."""
    def occupancy(root):
        placed = None if rows is None else [{"source": "registry" if oracle == "registry" else "marker", **r}
                                            for r in rows]
        return types.SimpleNamespace(
            sessions=placed, oracle=oracle, note=note, caller=caller,
            from_registry=lambda: [r for r in placed or [] if r["source"] == "registry"])
    return types.SimpleNamespace(
        occupancy=occupancy,
        describe_session=lambda row: f"pid {row['pid']} ({row['entrypoint']})",
        claude_config_dir=lambda: Path("cfg"),
    )


@pytest.fixture
def ship():
    """A fresh copy of the script per row: each row replaces its runner, and
    the liveness oracle reads nobody else in the checkout unless a row says so
    (the real one reads the box's own session registry)."""
    mod = _load()
    mod._SYNC = _oracle([])
    # The overlap notice after a push reads the mail, gh and git through the
    # board; TestTheNoticeAfterAPush stands its own board in.
    mod._BOARD = types.SimpleNamespace(lane_overlap_lines=lambda *a, **k: [])
    # The Session Log fold runs real git against the records refs; its own
    # rows are tests/test_mail.py::TestTheRecordsRef. Here it is a recorder,
    # noting where in the spawn order each fold ran.
    mod.FOLDS = []

    def _no_fold(root, base, *, keep=None, dry_run=False):
        calls = getattr(mod.RUN, "calls", None)
        mod.FOLDS.append({"base": base, "dry_run": dry_run, "at": len(calls) if calls is not None else -1})
        return 0, 0

    mod._fold_session_log = _no_fold
    return mod


@pytest.fixture
def forget_guard():
    """Drop the guard the script loads by path, so one row's fixture guard is
    never the next row's answer."""
    yield
    sys.modules.pop("_ship_ci_guard", None)


@pytest.fixture(autouse=True)
def _outside_a_session(monkeypatch):
    """The suite may run inside a Claude session, which exports its id to the
    shell; the handoff's last act arms the own-clear marker for that id (HEAD
    and the seat's brief read through real git), which these rows' fake runner
    does not describe. Without the id the arm stands down in one line, and
    TestTheHandoffArmsTheOwnClear stands the arm in by name."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)


# ── the recording runner ─────────────────────────────────────────────────────

#: Spawns that change something: the ones a refusal must not have reached.
_MUTATING_PREFIXES = (
    ("git", "push"),
    ("git", "pull"),
    ("git", "tag"),
    ("git", "switch"),
    ("git", "merge"),    # the merge-first step (not merge-tree, which only probes)
    ("git", "commit"),
    ("git", "add"),
    ("gh", "pr", "create"),
    ("gh", "pr", "edit"),
    ("gh", "pr", "merge"),
    ("gh", "pr", "update-branch"),
    ("gh", "release", "create"),
    ("gh", "run", "rerun"),
)


def _is_mutation(argv: list[str]) -> bool:
    if argv[:2] == ["git", "branch"]:
        return "--show-current" not in argv  # naming a lane, or moving a ref
    return any(tuple(argv[: len(prefix)]) == prefix for prefix in _MUTATING_PREFIXES)


class _Spawns:
    """The stand-in for ship.RUN: a table of argv-prefix -> answer, the calls
    made in order, and an AssertionError on a spawn the table does not describe
    (an unplanned spawn is a test that stopped describing the verb, not a pass).

    An answer may be a list, consumed in call order for that prefix and held at
    the last entry after: the `open` verb lists the branch's pull requests once
    before the push and again after the create, and the two answers differ.
    """

    def __init__(self, answers: dict[tuple[str, ...], object]):
        self._answers = dict(answers)
        self._seen: dict[tuple[str, ...], int] = {}
        self.calls: list[list[str]] = []
        self.kwargs: list[dict] = []
        #: What a `--body-file` argument pointed at, read while it still existed,
        #: byte-faithfully: a carriage return survives the read, so a doubled
        #: line break is visible to the test on every host.
        self.body_texts: list[str] = []

    def __call__(self, argv, **kw):
        argv = list(argv)
        self.calls.append(argv)
        self.kwargs.append(dict(kw))
        if "--body-file" in argv:
            path = Path(argv[argv.index("--body-file") + 1])
            if path.is_file():
                # newline="": a universal-newline read folds \r\n to \n and hides
                # the doubling this file exists to see. Keep it on the read.
                with path.open(encoding="utf-8", newline="") as fh:
                    self.body_texts.append(fh.read())
            else:
                self.body_texts.append("")
        key = self._match(argv)
        if key is None:
            raise AssertionError("unplanned spawn: " + " ".join(argv))
        nth = self._seen.get(key, 0)
        self._seen[key] = nth + 1
        answer = self._answers[key]
        if isinstance(answer, list):
            answer = answer[min(nth, len(answer) - 1)]
        return answer

    def _match(self, argv: list[str]) -> tuple[str, ...] | None:
        best: tuple[str, ...] | None = None
        for key in self._answers:
            if tuple(argv[: len(key)]) == key and (best is None or len(key) > len(best)):
                best = key
        return best

    # -- what the rows ask of the record ------------------------------------
    def matching(self, prefix: tuple[str, ...]) -> list[list[str]]:
        return [c for c in self.calls if tuple(c[: len(prefix)]) == prefix]

    def count(self, prefix: tuple[str, ...]) -> int:
        return len(self.matching(prefix))

    def index(self, prefix: tuple[str, ...]) -> int:
        for i, c in enumerate(self.calls):
            if tuple(c[: len(prefix)]) == prefix:
                return i
        return -1

    @property
    def mutations(self) -> list[str]:
        return [" ".join(c) for c in self.calls if _is_mutation(c)]


class _Clock:
    """The script's clock, stood in: sleeping advances it, so a bounded wait
    reaches its deadline in no wall-clock time."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(float(seconds), 0.001)


def _bind_clock(ship, monkeypatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(ship, "time", types.SimpleNamespace(
        monotonic=clock.monotonic, sleep=clock.sleep))
    return clock


def _arm(ship, answers: dict) -> _Spawns:
    spawns = _Spawns(answers)
    ship.RUN = spawns
    return spawns


# ── answer tables ────────────────────────────────────────────────────────────

def _reads(root, branch: str = "lane/x", base: str = "main") -> dict:
    """The three reads a verb opens with: the checkout, the default branch,
    the branch HEAD sits on."""
    return {
        ("git", "rev-parse", "--show-toplevel"): (0, f"{root}\n", ""),
        ("gh", "repo", "view"): (0, f"{base}\n", ""),
        ("git", "branch", "--show-current"): (0, f"{branch}\n", ""),
        ("git", "rev-parse", "-q", "--verify", "MERGE_HEAD"): (1, "", ""),   # no merge in progress
    }


def _pr(number: int = 7, title: str = "feat: a thing", state: str = "OPEN",
        head: str = HEAD, merge_state: str = "CLEAN", armed: bool = True,
        merge_oid: str | None = None, mergeable: str = "MERGEABLE", base: str = "main") -> dict:
    return {
        "number": number,
        "title": title,
        "url": f"https://example.invalid/pull/{number}",
        "state": state,
        "headRefOid": head,
        "baseRefName": base,
        "mergeStateStatus": merge_state,
        "mergeable": mergeable,
        "autoMergeRequest": {"enabledAt": "2026-09-30T00:00:00Z"} if armed else None,
        "mergeCommit": {"oid": merge_oid} if merge_oid else None,
    }


def _rows(*rows: dict) -> tuple[int, str, str]:
    return (0, json.dumps(list(rows)), "")


def _list_key(branch: str = "lane/x", state: str = "open") -> tuple[str, ...]:
    return ("gh", "pr", "list", "--head", branch, "--state", state)


def _write_guard(root: Path, source: str = _GUARD_SOURCE) -> Path:
    guard = root / "tools" / "cc" / "ci_guard.py"
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_text(source, encoding="utf-8")
    return guard


# ── the one spawn ────────────────────────────────────────────────────────────

class TestRunner:
    """ship.run: the chokepoint every verb spawns through."""

    @staticmethod
    def _stub(ship, monkeypatch, *, which="/usr/bin/gh", raises=None,
              answer=(0, "out", "err")):
        spawned: list[dict] = []

        def fake_run(argv, **kw):
            spawned.append({"argv": list(argv), "kw": dict(kw)})
            if raises is not None:
                raise raises
            rc, out, err = answer
            return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)

        monkeypatch.setattr(ship, "shutil", types.SimpleNamespace(
            which=lambda name: which))
        # ship.run spawns through the bounded spawn (2026-10-13); the stub
        # stands in for it, and the namespace keeps the names run still reads.
        monkeypatch.setattr(ship, "run_bounded", fake_run)
        monkeypatch.setattr(ship, "subprocess", types.SimpleNamespace(
            DEVNULL=subprocess.DEVNULL, TimeoutExpired=subprocess.TimeoutExpired))
        return spawned

    def test_the_program_is_resolved_on_path_so_a_bare_name_finds_a_windows_exe(
            self, ship, monkeypatch):
        spawned = self._stub(ship, monkeypatch, which="C:/hostedtoolcache/gh.exe")
        ship.run(["gh", "pr", "list"])
        assert spawned[0]["argv"] == ["C:/hostedtoolcache/gh.exe", "pr", "list"]

    def test_a_spawn_without_input_closes_stdin_and_carries_an_encoding_and_a_timeout(
            self, ship, monkeypatch):
        spawned = self._stub(ship, monkeypatch)
        ship.run(["gh", "pr", "list"])
        kw = spawned[0]["kw"]
        assert kw["stdin"] is subprocess.DEVNULL
        assert "input" not in kw
        assert kw["encoding"] == "utf-8"
        assert kw["timeout"] == ship.DEFAULT_TIMEOUT

    def test_given_input_replaces_the_closed_stdin(self, ship, monkeypatch):
        spawned = self._stub(ship, monkeypatch)
        ship.run(["gh", "pr", "comment"], input="a body")
        kw = spawned[0]["kw"]
        assert kw["input"] == "a body"
        assert "stdin" not in kw

    def test_a_missing_program_is_a_named_refusal_and_nothing_is_spawned(
            self, ship, monkeypatch):
        spawned = self._stub(ship, monkeypatch, which=None)
        with pytest.raises(ship.Refused) as stop:
            ship.run(["gh", "pr", "list"])
        assert "not on PATH" in str(stop.value)
        assert spawned == []

    def test_a_spawn_that_outlives_its_timeout_is_a_named_refusal(self, ship, monkeypatch):
        self._stub(ship, monkeypatch,
                   raises=subprocess.TimeoutExpired(cmd="gh", timeout=60))
        with pytest.raises(ship.Refused) as stop:
            ship.run(["gh", "pr", "list"])
        assert "took longer than" in str(stop.value)

    def test_a_program_that_cannot_start_is_a_named_refusal(self, ship, monkeypatch):
        self._stub(ship, monkeypatch, raises=OSError("exec format error"))
        with pytest.raises(ship.Refused) as stop:
            ship.run(["gh", "pr", "list"])
        assert "could not run gh" in str(stop.value)


# ── the marker ───────────────────────────────────────────────────────────────

class TestBind:
    def test_every_earlier_binding_is_stripped_and_exactly_one_is_appended(self, ship):
        stale = f"feat: a thing {MARKER}@0000000 {MARKER}@1111111"
        bound = ship.bind(stale, HEAD)
        assert bound.count(MARKER) == 1
        assert bound == f"feat: a thing {MARKER}@{SHORT}"

    def test_a_title_with_no_binding_takes_one(self, ship):
        assert ship.bind("feat: a thing", HEAD) == f"feat: a thing {MARKER}@{SHORT}"

    def test_a_word_that_merely_contains_the_marker_text_survives(self, ship):
        bound = ship.bind(f"feat: mention {MARKER}@deadbeefzz here", HEAD)
        assert "deadbeefzz" in bound
        assert bound.endswith(f"{MARKER}@{SHORT}")


# ── preflight ────────────────────────────────────────────────────────────────

def _preflight_answers(root, *, dirty="", untracked="", commits="abc1234 feat: a thing\n",
                       merged="[]", base_runs="[]") -> dict:
    answers = _reads(root)
    answers.update({
        ("git", "fetch", "origin", "--quiet"): (0, "", ""),
        ("git", "status", "--porcelain", "-uno"): (0, dirty, ""),
        ("git", "status", "--porcelain", "--untracked-files=all"): (0, untracked, ""),
        ("git", "log", "--oneline"): (0, commits, ""),
        ("git", "merge-tree"): (0, "abc123\n", ""),   # the merge verdict: clean unless a test says otherwise
        ("git", "diff", "--name-only"): (0, "", ""),   # the attribute walk: nothing changed on both sides
        ("gh", "pr", "list", "--state"): (0, merged, ""),   # no author filter: every seat pushes as one account
        ("gh", "run", "list", "--workflow", "post-merge.yml"): (0, base_runs, ""),
        _ROW_FILES: _row_log(),   # no row added by the lane's own commits
    })
    return answers


def _memory(root: Path, *dates: str) -> None:
    rows = "".join(f"| {d} | a session row |\n" for d in dates)
    (root / "ESPALIER_MEMORY.md").write_text(
        "| Date | What |\n|---|---|\n" + rows, encoding="utf-8")


#: The read that asks whether this lane's own commits touch the memory file.
_MEMORY_LOG = ("git", "log", "--format=%h")
#: The read that asks whether this lane's own commits added a Session Log file
#: (the row's home since 2026-10-10), each commit's fold trailer (read by key)
#: beside its names so a fold commit's rows are told apart.
_ROW_FILES = ("git", "log", "--format=%x1e%(trailers:key=Espalier-Fold,valueonly)%x1f")
#: The handoff's question: does this lane carry anything but Session Log rows?
_LANE_DIFF = ("git", "diff", "--name-status")
#: A fold commit's trailer value, as the row read prints it.
_FOLD = "session-log"


def _row_log(*commits: tuple[str, list[str]]) -> tuple[int, str, str]:
    """The row read's answer: ``(fold trailer value or "", added paths)`` per commit."""
    return 0, "".join(f"\x1e{value}\x1f\n" + "".join(f"{p}\n" for p in paths) for value, paths in commits), ""


def _toml(root: Path, text: str) -> None:
    (root / "espalier.toml").write_text(text, encoding="utf-8")


class TestPreflight:
    # The date-keyed handoff notice these rows replaced read only the newest
    # memory row's date, so a second lane on the same day got no notice (it
    # said so itself) and a mid-session ship made the handoff a second push
    # (2026-10-03). The notice is now per lane, and only where the repo opted
    # into handoff pushes: see TestTheLaneCarriesItsMemoryRowWhenHandoffPushes.
    def test_with_handoff_push_off_preflight_says_nothing_about_the_handoff(
            self, ship, tmp_path, capsys):
        _memory(tmp_path, "2026-09-28", "2026-09-29")
        spawns = _arm(ship, _preflight_answers(tmp_path))
        assert ship.preflight() == 0
        assert "handoff" not in capsys.readouterr().out
        assert spawns.count(_MEMORY_LOG) == 0

    def test_untracked_files_are_noted_and_do_not_stop_the_ship(
            self, ship, tmp_path, capsys):
        _memory(tmp_path, "2026-09-30")
        spawns = _arm(ship, _preflight_answers(
            tmp_path, untracked="?? scratch.txt\n?? notes.md\n M tracked.py\n"))
        assert ship.preflight() == 0
        out = capsys.readouterr().out
        assert "2 untracked file(s) will not ship" in out
        assert "scratch.txt" in out
        assert spawns.mutations == []

    def test_a_dirty_tracked_tree_is_refused_before_anything_mutates(
            self, ship, tmp_path):
        spawns = _arm(ship, _preflight_answers(tmp_path, dirty=" M CLAUDE.md\n"))
        with pytest.raises(ship.Refused) as stop:
            ship.preflight()
        assert "the tracked tree is dirty" in str(stop.value)
        assert spawns.mutations == []

    def test_an_empty_commit_range_is_refused(self, ship, tmp_path):
        spawns = _arm(ship, _preflight_answers(tmp_path, commits="\n"))
        with pytest.raises(ship.Refused) as stop:
            ship.preflight()
        assert "nothing to ship" in str(stop.value)
        assert spawns.mutations == []

    def test_a_merged_pull_request_whose_newest_run_is_red_is_named(
            self, ship, tmp_path, capsys):
        _memory(tmp_path, "2026-09-30")
        merged = json.dumps([{"number": 41, "statusCheckRollup": [
            {"name": "portability", "startedAt": "2026-09-29T10:00:00Z",
             "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"name": "portability", "startedAt": "2026-09-29T11:00:00Z",
             "status": "COMPLETED", "conclusion": "FAILURE"},
        ]}])
        _arm(ship, _preflight_answers(tmp_path, merged=merged))
        assert ship.preflight() == 0
        assert "red after merge: #41 portability" in capsys.readouterr().out

    def test_an_older_red_run_is_not_named_once_the_newest_is_green(
            self, ship, tmp_path, capsys):
        _memory(tmp_path, "2026-09-30")
        merged = json.dumps([{"number": 41, "statusCheckRollup": [
            {"name": "portability", "startedAt": "2026-09-29T10:00:00Z",
             "status": "COMPLETED", "conclusion": "FAILURE"},
            {"name": "portability", "startedAt": "2026-09-29T11:00:00Z",
             "status": "COMPLETED", "conclusion": "SUCCESS"},
        ]}])
        _arm(ship, _preflight_answers(tmp_path, merged=merged))
        assert ship.preflight() == 0
        assert "red after merge" not in capsys.readouterr().out

    @staticmethod
    def _runs(*rows: tuple[str, str]) -> str:
        """Newest first, as `gh run list` returns them."""
        return json.dumps([
            {"databaseId": 900 + i, "status": status, "conclusion": conclusion,
             "headSha": f"{i}" * 40, "url": f"https://example/run/{900 + i}"}
            for i, (status, conclusion) in enumerate(rows)
        ])

    def test_a_red_post_merge_run_on_the_base_is_named(self, ship, tmp_path, capsys):
        """Without the up-to-date rule, two lanes each green on its own base can
        red together; the base's push run is where that shows, and no pull
        request's rollup carries it."""
        _memory(tmp_path, "2026-10-09")
        _arm(ship, _preflight_answers(tmp_path, base_runs=self._runs(
            ("completed", "failure"), ("completed", "success"))))
        assert ship.preflight() == 0
        assert "main red after merge: post-merge.yml run 900" in capsys.readouterr().out

    def test_a_green_newest_verdict_says_nothing(self, ship, tmp_path, capsys):
        _memory(tmp_path, "2026-10-09")
        _arm(ship, _preflight_answers(tmp_path, base_runs=self._runs(
            ("completed", "success"), ("completed", "failure"))))
        assert ship.preflight() == 0
        assert "red after merge" not in capsys.readouterr().out

    def test_a_cancelled_or_running_newest_run_defers_to_the_last_verdict(
            self, ship, tmp_path, capsys):
        _memory(tmp_path, "2026-10-09")
        _arm(ship, _preflight_answers(tmp_path, base_runs=self._runs(
            ("in_progress", ""), ("completed", "cancelled"), ("completed", "success"))))
        assert ship.preflight() == 0
        assert "red after merge" not in capsys.readouterr().out
        _arm(ship, _preflight_answers(tmp_path, base_runs=self._runs(
            ("in_progress", ""), ("completed", "cancelled"), ("completed", "failure"))))
        assert ship.preflight() == 0
        assert "main red after merge: post-merge.yml run 902" in capsys.readouterr().out

    def test_a_skipped_or_neutral_run_is_no_verdict(self, ship, tmp_path, capsys):
        """A run skipped by a job-level `if`, or concluding neutral, is no
        verdict: read as red, it would ask a seat to revert a merge on a green
        base (the board's review, 2026-10-09). Dies to: every non-SUCCESS
        conclusion read as red."""
        _memory(tmp_path, "2026-10-09")
        _arm(ship, _preflight_answers(tmp_path, base_runs=self._runs(
            ("completed", "skipped"), ("completed", "neutral"), ("completed", "success"))))
        assert ship.preflight() == 0
        assert "red after merge" not in capsys.readouterr().out

    def test_a_tree_that_is_not_a_git_checkout_is_refused(self, ship, tmp_path):
        answers = _preflight_answers(tmp_path)
        answers[("git", "rev-parse", "--show-toplevel")] = (128, "", "not a repository")
        spawns = _arm(ship, answers)
        with pytest.raises(ship.Refused) as stop:
            ship.preflight()
        assert "not inside a git checkout" in str(stop.value)
        assert spawns.mutations == []

    def test_a_default_branch_gh_cannot_name_is_refused(self, ship, tmp_path):
        answers = _preflight_answers(tmp_path)
        answers[("gh", "repo", "view")] = (1, "", "gh: not logged in")
        spawns = _arm(ship, answers)
        with pytest.raises(ship.Refused) as stop:
            ship.preflight()
        assert "gh could not name the default branch" in str(stop.value)
        assert "not logged in" in str(stop.value)
        assert spawns.mutations == []

    def test_a_gh_read_that_answers_without_json_is_refused(self, ship, tmp_path):
        _memory(tmp_path, "2026-09-30")
        spawns = _arm(ship, _preflight_answers(tmp_path, merged="<html>a login page</html>"))
        with pytest.raises(ship.Refused) as stop:
            ship.preflight()
        assert "with no JSON" in str(stop.value)
        assert spawns.mutations == []


# ── lane ─────────────────────────────────────────────────────────────────────

def _lane_answers(root, *, branch="main", subject="feat: a thing", create=(0, "", ""),
                  switch=(0, "", ""), reset=(0, "", "")) -> dict:
    answers = _reads(root, branch=branch)
    answers.update({
        ("git", "log", "-1"): (0, f"{subject}\n", ""),
        ("git", "branch", "lane/feat-a-thing"): create,
        ("git", "switch", "lane/feat-a-thing"): switch,
        ("git", "branch", "-f"): reset,
    })
    return answers


class TestLane:
    def test_the_lane_is_named_and_entered_before_the_default_branch_is_reset(
            self, ship, tmp_path, capsys):
        spawns = _arm(ship, _lane_answers(tmp_path))
        assert ship.lane() == 0
        named = spawns.index(("git", "branch", "lane/feat-a-thing"))
        entered = spawns.index(("git", "switch", "lane/feat-a-thing"))
        reset = spawns.index(("git", "branch", "-f"))
        assert named >= 0 and named < entered < reset
        assert "moved the unmerged commits to lane/feat-a-thing" in capsys.readouterr().out

    def test_off_the_default_branch_nothing_moves(self, ship, tmp_path, capsys):
        spawns = _arm(ship, _lane_answers(tmp_path, branch="lane/x"))
        assert ship.lane() == 0
        assert "nothing to move" in capsys.readouterr().out
        assert spawns.mutations == []

    def test_a_subject_that_yields_no_lane_name_is_refused_before_anything_mutates(
            self, ship, tmp_path):
        spawns = _arm(ship, _lane_answers(tmp_path, subject="!!! ???"))
        with pytest.raises(ship.Refused) as stop:
            ship.lane()
        assert "yields no lane name" in str(stop.value)
        assert spawns.mutations == []

    def test_a_lane_name_that_cannot_be_created_is_refused_before_the_switch(
            self, ship, tmp_path):
        spawns = _arm(ship, _lane_answers(tmp_path, create=(1, "", "already exists")))
        with pytest.raises(ship.Refused) as stop:
            ship.lane()
        assert "could not create lane/feat-a-thing" in str(stop.value)
        assert spawns.count(("git", "switch",)) == 0
        assert spawns.count(("git", "branch", "-f")) == 0

    def test_a_failed_switch_leaves_the_default_branch_where_the_commits_are(
            self, ship, tmp_path):
        spawns = _arm(ship, _lane_answers(tmp_path, switch=(1, "", "index would be lost")))
        with pytest.raises(ship.Refused) as stop:
            ship.lane()
        assert "could not switch to lane/feat-a-thing" in str(stop.value)
        assert spawns.count(("git", "branch", "-f")) == 0

    def test_a_default_branch_that_cannot_be_reset_is_refused_and_names_the_lane(
            self, ship, tmp_path):
        _arm(ship, _lane_answers(tmp_path, reset=(1, "", "not a valid ref")))
        with pytest.raises(ship.Refused) as stop:
            ship.lane()
        assert "lane/feat-a-thing holds the commits" in str(stop.value)
        assert "could not be reset" in str(stop.value)

    def test_a_detached_head_is_refused_before_anything_mutates(self, ship, tmp_path):
        answers = _lane_answers(tmp_path)
        answers[("git", "branch", "--show-current")] = (0, "\n", "")
        spawns = _arm(ship, answers)
        with pytest.raises(ship.Refused) as stop:
            ship.lane()
        assert "detached HEAD" in str(stop.value)
        assert spawns.mutations == []


# ── open ─────────────────────────────────────────────────────────────────────

def _open_answers(root, *, branch="lane/x", base="main", existing="[]",
                  behind="0\n", push=(0, "", ""), diff="tools/cc/ship.py\ndocs/HOOKS.md\n",
                  create=(0, "https://example.invalid/pull/7\n", ""),
                  merge=(0, "", ""), armed='{"autoMergeRequest": {"enabledAt": "x"}}',
                  open_prs="[]", base_runs="[]") -> dict:
    answers = _reads(root, branch=branch, base=base)
    answers.update({
        _list_key(branch): [(0, existing, ""), _rows(_pr())],
        ("gh", "pr", "list", "--state", "open"): (0, open_prs, ""),   # the red-base and one-per-seat reads
        ("gh", "run", "list", "--workflow", "post-merge.yml"): (0, base_runs, ""),
        ("git", "fetch", "origin", branch): (0, "", ""),
        ("git", "fetch"): (0, "", ""),   # the base, fetched before the guard question
        ("git", "merge-tree"): (0, "abc123\n", ""),   # the merge-first probe: clean unless a test says otherwise
        ("git", "diff", "--name-only", "HEAD...origin/main"): (0, "", ""),   # the base changed nothing we did
        ("git", "rev-list", "--count"): (0, behind, ""),
        ("git", "rev-parse", "HEAD"): (0, f"{HEAD}\n", ""),
        ("git", "log", "-1"): (0, "feat: a thing\n", ""),
        ("git", "log", "--format=- %s"): (0, "- feat: a thing\n", ""),
        ("git", "push"): push,
        ("git", "diff", "--name-only"): (0, diff, ""),
        _LANE_DIFF: (0, "".join(f"M\t{p}\n" for p in diff.split()), ""),   # a lane with code: no park
        _ROW_FILES: _row_log(),   # no row added by the lane's own commits
        ("gh", "label", "create"): (0, "", ""),   # the seat label, stamped where the box is named
        ("gh", "pr", "create"): create,
        ("gh", "pr", "merge"): merge,
        ("gh", "pr", "view"): (0, armed, ""),
    })
    return answers


class TestOpen:
    def test_a_protected_diff_opens_the_pull_request_with_the_marker_already_bound(
            self, ship, tmp_path, forget_guard, capsys):
        _write_guard(tmp_path)
        body = tmp_path / "body.md"
        body.write_text("the lane's story\n", encoding="utf-8")
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr(body_file=str(body)) == 0
        created = spawns.matching(("gh", "pr", "create"))
        assert len(created) == 1
        title = created[0][created[0].index("--title") + 1]
        assert title == f"feat: a thing {MARKER}@{SHORT}"
        assert title.count(MARKER) == 1
        # One event, one run: the binding rides in the create, never an edit.
        assert spawns.count(("gh", "pr", "edit")) == 0
        assert "--body-file" in created[0]
        assert spawns.body_texts == ["the lane's story\n"]
        assert "marker required (tools/cc/ship.py)" in capsys.readouterr().out

    def test_a_crlf_body_file_reaches_the_pull_request_as_bare_line_feeds(
            self, ship, tmp_path, forget_guard):
        """A body saved with CRLF endings (a Windows editor, a text-mode write)
        ships to `gh pr create` as bare line feeds. Before this pin the driver
        kept the carriage returns and wrote them through a text-mode temp file,
        so on Windows every line break reached GitHub doubled: the portability
        cell read the lane's story back with two newlines (2026-10-01). The fake
        runner reads the temp file with newline="" so the defect is visible on
        every host, not only the one that doubles."""
        _write_guard(tmp_path)
        body = tmp_path / "body.md"
        body.write_bytes(b"the lane's story\r\n\r\nsecond paragraph\r\n")
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr(body_file=str(body)) == 0
        assert spawns.body_texts == ["the lane's story\n\nsecond paragraph\n"]
        assert "\r" not in spawns.body_texts[0]

    def test_a_body_file_in_a_windows_default_encoding_is_refused_by_name(
            self, ship, tmp_path, forget_guard):
        """A body saved by a Windows editor in cp1252 is not UTF-8; the driver
        refuses before the push, naming the file and the encoding to re-save
        in, where it used to die on the decoder's traceback (code review,
        2026-10-01: `decode_bom` raises a ValueError the OSError arm never
        caught)."""
        _write_guard(tmp_path)
        body = tmp_path / "body.md"
        body.write_bytes("the lane\u2019s story\n".encode("cp1252"))
        spawns = _arm(ship, _open_answers(tmp_path))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr(body_file=str(body))
        assert "body.md" in str(stop.value) and "not UTF-8 text" in str(stop.value)
        assert "re-save it as UTF-8" in str(stop.value)
        assert spawns.count(("git", "push")) == 0 and spawns.count(("gh", "pr", "create")) == 0

    def test_the_pull_request_carries_the_seats_label_where_the_box_is_named(
            self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        """DEF-4044: a merged lane no claim names was nobody's, so the Session
        Log debt read it as zero and the cap was passed by not claiming. The
        seat:<machine> label rides the create, after the repository's copy of
        the label is made (gh pr create fails whole on a label the repository
        lacks); a label that could not be made is a note and the pull request
        opens without it; an unnamed box asks for none. Dies to: no label; the
        label passed when its creation failed; the label created before the
        push (a remote write before the lane is on origin)."""
        _write_guard(tmp_path)
        channel = ship._mail_module()
        monkeypatch.setattr(channel, "machine_setting", lambda root, **kw: ("win", "stubbed"))
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        created = spawns.matching(("gh", "pr", "create"))[0]
        assert created[created.index("--label") + 1] == "seat:win"
        labels = spawns.matching(("gh", "label", "create"))
        assert len(labels) == 1 and labels[0][3] == "seat:win" and "--force" in labels[0]
        assert spawns.index(("git", "push")) < spawns.index(("gh", "label", "create")) < spawns.index(("gh", "pr", "create"))
        answers = _open_answers(tmp_path)
        answers[("gh", "label", "create")] = (1, "", "HTTP 403: Resource not accessible")
        spawns = _arm(ship, answers)
        assert ship.open_pr() == 0
        assert "--label" not in spawns.matching(("gh", "pr", "create"))[0]
        assert "seat label seat:win could not be created (HTTP 403" in capsys.readouterr().out
        # A label create that times out raises in the runner: the pull request still opens, without the label.
        spawns = _arm(ship, _open_answers(tmp_path))
        real_gh = ship._gh

        def slow_gh(*a, **k):
            if a[:2] == ("label", "create"):
                raise ship.Refused("gh label create took longer than 60s")
            return real_gh(*a, **k)

        monkeypatch.setattr(ship, "_gh", slow_gh)
        assert ship.open_pr() == 0
        assert spawns.count(("gh", "pr", "create")) == 1 and "--label" not in spawns.matching(("gh", "pr", "create"))[0]
        assert "could not be created (gh label create took longer than 60s)" in capsys.readouterr().out
        monkeypatch.setattr(ship, "_gh", real_gh)
        monkeypatch.setattr(channel, "machine_setting", lambda root, **kw: (None, "git config espalier.machine is not set"))
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        assert spawns.count(("gh", "label", "create")) == 0 and "--label" not in spawns.matching(("gh", "pr", "create"))[0]
        assert "seat name could not be read" not in capsys.readouterr().out   # an unset name stays silent
        unread = channel.MACHINE_UNREAD
        monkeypatch.setattr(channel, "machine_setting", lambda root, **kw: (None, f"{unread} (git config took longer than 10s)"))
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        assert spawns.count(("gh", "label", "create")) == 0
        assert "seat name could not be read" in capsys.readouterr().out   # a name read that failed is said


# ── handoff_push: the /handoff push is a stated, committed choice ─────────────

class TestHandoffPushSetting:
    """`handoff_push` in espalier.toml decides whether /handoff pushes. Absent
    means off: a push is outward-facing, and two field-trial adopters found that
    nothing but the agent's vigilance told a new user /handoff pushes."""

    def test_an_absent_file_is_off_by_default(self, ship, tmp_path):
        on, how = ship.handoff_push_setting(tmp_path)
        assert on is False and "default" in how

    def test_an_absent_key_is_off_by_default(self, ship, tmp_path):
        _toml(tmp_path, 'plan_exempt_prefixes = ["x/"]\n')
        on, how = ship.handoff_push_setting(tmp_path)
        assert on is False and "does not set handoff_push" in how

    @pytest.mark.parametrize("value,expected", [("true", True), ("false", False)])
    def test_an_explicit_value_is_read_and_named(self, ship, tmp_path, value, expected):
        _toml(tmp_path, f"# a comment\nhandoff_push = {value}  # trailing note\n")
        on, how = ship.handoff_push_setting(tmp_path)
        assert on is expected and f"handoff_push = {value}" in how

    @pytest.mark.parametrize("value", ['"true"', "yes", "1", "True"])
    def test_a_value_that_is_not_true_or_false_reads_as_off_and_is_named(self, ship, tmp_path, value):
        _toml(tmp_path, f"handoff_push = {value}\n")
        on, how = ship.handoff_push_setting(tmp_path)
        assert on is False and value in how and "neither true nor false" in how

    def test_a_key_under_a_table_is_not_the_setting_and_says_where_it_was(self, ship, tmp_path):
        _toml(tmp_path, "[tool.other]\nhandoff_push = true\n")
        on, how = ship.handoff_push_setting(tmp_path)
        assert on is False and "under [tool.other]" in how

    def test_a_nested_array_line_is_not_mistaken_for_a_table_header(self, ship, tmp_path):
        """Review, 2026-10-03: the first cut stopped at any line opening with `[`,
        which a nested array element inside a multi-line value also does."""
        _toml(tmp_path, 'pairs = [\n  ["a", "b"],\n]\nhandoff_push = true\n')
        assert ship.handoff_push_setting(tmp_path)[0] is True

    def test_a_quoted_key_is_the_same_key(self, ship, tmp_path):
        _toml(tmp_path, '"handoff_push" = true\n')
        assert ship.handoff_push_setting(tmp_path)[0] is True

    @pytest.mark.parametrize("spelling", ["handoff-push", "Handoff_Push"])
    def test_a_near_miss_spelling_is_named_not_silent(self, ship, tmp_path, spelling):
        _toml(tmp_path, f"{spelling} = true\n")
        on, how = ship.handoff_push_setting(tmp_path)
        assert on is False and spelling in how

    def test_this_repository_opts_in(self, ship):
        """The two-machine operator's setting: deleting the key would turn every
        handoff push off between the machines with nothing red."""
        if not (ROOT / "espalier.toml").is_file():
            pytest.skip("no espalier.toml in this tree (an extracted archive does not carry it)")
        on, how = ship.handoff_push_setting(ROOT)
        assert on is True, how

    def test_a_commented_out_line_is_not_the_setting(self, ship, tmp_path):
        _toml(tmp_path, "# handoff_push = true\n")
        assert ship.handoff_push_setting(tmp_path)[0] is False

    def test_a_byte_order_mark_does_not_hide_the_key(self, ship, tmp_path):
        (tmp_path / "espalier.toml").write_bytes(b"\xef\xbb\xbfhandoff_push = true\n")
        assert ship.handoff_push_setting(tmp_path)[0] is True

    def test_the_key_is_declared_where_the_engine_warns_on_unknown_keys(self):
        """espalier/config.py warns on every top-level key it does not own; a key
        a script reads must be declared there, or every load of the tree warns
        and the obvious response, deleting the key, turns the push off."""
        from espalier.config import FOREIGN_KEYS
        assert FOREIGN_KEYS.get("handoff_push") == "tools/cc/ship.py"


class TestHandoffVerb:
    """`ship.py handoff` is /handoff's one push step, governed by the setting."""

    def test_off_pushes_nothing_and_says_how_to_push_and_how_to_enable(self, ship, tmp_path, capsys):
        answers = _reads(tmp_path)
        answers[_list_key()] = (0, "[]", "")
        spawns = _arm(ship, answers)
        assert ship.handoff() == 0
        out = capsys.readouterr().out
        assert "handoff push is off" in out
        assert "/ship" in out and "handoff_push = true" in out
        assert spawns.mutations == []

    def test_off_with_an_open_pull_request_says_it_will_merge_without_this_commit(
            self, ship, tmp_path, capsys):
        """Review, 2026-10-03: with the setting off, a lane shipped mid-session
        merges without the handoff's row, which then sits on a merged branch."""
        answers = _reads(tmp_path)
        answers[_list_key()] = _rows(_pr())
        spawns = _arm(ship, answers)
        assert ship.handoff() == 0
        out = capsys.readouterr().out
        assert "#7 is open" in out and "WITHOUT this commit" in out and "rebind" in out
        assert spawns.mutations == []

    def test_on_with_no_pull_request_opens_one(self, ship, tmp_path, forget_guard, capsys):
        _toml(tmp_path, "handoff_push = true\n")
        _write_guard(tmp_path)
        answers = _open_answers(tmp_path)
        answers[("git", "status", "--porcelain", "-uno")] = (0, "", "")
        answers[_MEMORY_LOG] = (0, "abc1234\n", "")   # the handoff's own commit is in range
        # handoff asks "is a pull request open?" once and open asks again before
        # creating one: two empty answers, then the created pull request
        answers[_list_key()] = [(0, "[]", ""), (0, "[]", ""), _rows(_pr())]
        spawns = _arm(ship, answers)
        assert ship.handoff() == 0
        assert spawns.count(("git", "push")) == 1 and spawns.count(("gh", "pr", "create")) == 1
        assert "handoff push is on" in capsys.readouterr().out

    def test_on_with_an_open_pull_request_pushes_then_rebinds(self, ship, tmp_path, monkeypatch):
        _toml(tmp_path, "handoff_push = true\n")
        answers = self._existing_pr_answers(tmp_path)
        spawns = _arm(ship, answers)
        order: list[str] = []
        monkeypatch.setattr(ship, "rebind", lambda dry_run=False: order.append(
            f"rebind after {spawns.count(('git', 'push'))} push") or 0)
        assert ship.handoff() == 0
        assert order == ["rebind after 1 push"]
        assert spawns.count(("gh", "pr", "create")) == 0

    @staticmethod
    def _existing_pr_answers(tmp_path, heads=(HEAD,), base_runs="[]"):
        answers = _reads(tmp_path)
        answers.update({
            _list_key(): [_rows(_pr(head=h)) for h in heads],
            ("gh", "run", "list", "--workflow", "post-merge.yml"): (0, base_runs, ""),   # a red base is said
            ("git", "status", "--porcelain", "-uno"): (0, "", ""),
            ("git", "fetch", "origin", "lane/x"): (0, "", ""),
            ("git", "fetch", "origin", "main"): (0, "", ""),   # the base, before the merge-first probe
            ("git", "merge-tree"): (0, "abc123\n", ""),         # clean: nothing to merge first
            ("git", "diff", "--name-only"): (0, "", ""),        # the attribute walk: nothing changed on both sides
            ("git", "rev-list", "--count"): (0, "0\n", ""),
            ("git", "rev-parse", "HEAD"): (0, f"{HEAD}\n", ""),
            ("git", "push"): (0, "", ""),
        })
        return answers

    def test_the_rebind_waits_for_github_to_report_the_new_head(self, ship, tmp_path, monkeypatch):
        """Met 2026-10-03: a rebind read right after the push saw the old head and
        refused with "push first" although the push had landed."""
        _toml(tmp_path, "handoff_push = true\n")
        old = "0" * 40
        spawns = _arm(ship, self._existing_pr_answers(tmp_path, heads=(old, old, HEAD)))
        _bind_clock(ship, monkeypatch)
        rebinds: list[int] = []
        monkeypatch.setattr(ship, "rebind", lambda dry_run=False: rebinds.append(
            spawns.count(_list_key())) or 0)
        assert ship.handoff() == 0
        assert rebinds == [3]   # existence check, one stale read, then the new head

    def test_a_dirty_tree_is_refused_before_the_push(self, ship, tmp_path):
        _toml(tmp_path, "handoff_push = true\n")
        answers = self._existing_pr_answers(tmp_path)
        answers[("git", "status", "--porcelain", "-uno")] = (0, " M tools/cc/ship.py\n", "")
        spawns = _arm(ship, answers)
        with pytest.raises(ship.Refused) as stop:
            ship.handoff()
        assert "the tracked tree is dirty" in str(stop.value)
        assert spawns.mutations == []

    def test_dry_run_from_the_default_branch_moves_nothing(self, ship, tmp_path, capsys):
        """Both reviews, 2026-10-03: `handoff --dry-run` from the default branch
        called `lane`, which creates a branch, switches to it and resets the
        default branch."""
        _toml(tmp_path, "handoff_push = true\n")
        answers = _reads(tmp_path, branch="main")
        answers[("git", "status", "--porcelain", "-uno")] = (0, "", "")
        answers[("git", "fetch")] = (0, "", "")
        answers[_LANE_DIFF] = (0, "M\ttools/cc/ship.py\n", "")   # code: not a handoff-only lane
        spawns = _arm(ship, answers)
        assert ship.handoff(dry_run=True) == 0
        assert spawns.mutations == []
        assert "dry-run: `lane` would move" in capsys.readouterr().out

    def test_on_from_the_default_branch_moves_to_a_lane_first(self, ship, tmp_path, monkeypatch):
        _toml(tmp_path, "handoff_push = true\n")
        answers = _reads(tmp_path)
        answers[("git", "branch", "--show-current")] = [(0, "main\n", ""), (0, "lane/x\n", "")]
        answers[_list_key()] = (0, "[]", "")
        answers[("git", "status", "--porcelain", "-uno")] = (0, "", "")
        answers[("git", "fetch")] = (0, "", "")
        answers[_LANE_DIFF] = (0, "M\ttools/cc/ship.py\n", "")   # code: not a handoff-only lane
        _arm(ship, answers)
        order: list[str] = []
        monkeypatch.setattr(ship, "lane", lambda: order.append("lane") or 0)
        monkeypatch.setattr(ship, "open_pr", lambda **kw: order.append("open") or 0)
        assert ship.handoff() == 0
        assert order == ["lane", "open"]


class TestTheHandoffArmsTheOwnClear:
    """The handoff's last act arms the own-clear marker (``arm_own_clear_here``,
    its own rows in tests/test_own_clear.py) whenever the verb ran to its end
    on a clean tree with the row written: after the push has landed, on the
    off path once the verb has said its piece, and -- DEF-4057, measured
    2026-10-29 (win, win-2 and air-work frozen past the threshold for 17.5 h)
    -- after a refusal the window is done with: the red base (nothing lands
    on it; the lane stays here, whole) or a step after a landed push (the head
    wait, the rebind). Those arm with the refusal in the marker (``Held``) and
    re-raise it. Never on a dry run, and never on a refusal the window must fix
    first (a dirty tree, a shared checkout, a lane behind its remote): a marker
    there would clear a window with work in it. The own-clear mod
    (tools/cc/mods/own-clear) reads nothing else. Dies to: an arm before the
    rebind, an arm skipped after the red-base refusal, an arm on a dirty tree,
    or a dry run that arms."""

    @staticmethod
    def _armed(ship, monkeypatch) -> list[str]:
        order: list[str] = []
        monkeypatch.setattr(ship, "arm_own_clear_here",
                            lambda root, **kw: order.append("arm") or "own-clear armed (stand-in)")
        return order

    @staticmethod
    def _arm_calls(ship, monkeypatch) -> list[dict]:
        """The arm stood in by name, recording what the handoff hands it: the
        ``held`` refusal, or nothing on a landed handoff."""
        calls: list[dict] = []

        def stand_in(root, **kw):
            calls.append(dict(kw))
            return "own-clear armed (stand-in)"

        monkeypatch.setattr(ship, "arm_own_clear_here", stand_in)
        return calls

    @staticmethod
    def _red_base() -> str:
        """The base's newest post-merge run, red: the read `open` refuses on."""
        return json.dumps([{"databaseId": 900, "status": "completed", "conclusion": "failure",
                            "headSha": "b" * 40, "url": "https://example/run/900"}])

    def _red_base_answers(self, tmp_path) -> dict:
        """A lane with its row written and a clean tree, no pull request yet,
        on a base whose post-merge proof is red."""
        _toml(tmp_path, "handoff_push = true\n")
        _write_guard(tmp_path)
        answers = _open_answers(tmp_path, base_runs=self._red_base())
        answers[("git", "status", "--porcelain", "-uno")] = (0, "", "")
        answers[_MEMORY_LOG] = (0, "abc1234\n", "")
        answers[_list_key()] = [(0, "[]", ""), (0, "[]", "")]
        return answers

    def test_the_off_path_arms_once_the_verb_has_said_its_piece(self, ship, tmp_path, monkeypatch, capsys):
        order = self._armed(ship, monkeypatch)
        answers = _reads(tmp_path)
        answers[_list_key()] = (0, "[]", "")
        _arm(ship, answers)
        assert ship.handoff() == 0
        assert order == ["arm"]
        out = capsys.readouterr().out
        assert out.index("handoff push is off") < out.index("own-clear armed")

    def test_the_push_onto_an_open_pull_request_arms_after_the_rebind(self, ship, tmp_path, monkeypatch):
        _toml(tmp_path, "handoff_push = true\n")
        spawns = _arm(ship, TestHandoffVerb._existing_pr_answers(tmp_path))
        order = self._armed(ship, monkeypatch)
        monkeypatch.setattr(ship, "rebind", lambda dry_run=False: order.append(
            f"rebind after {spawns.count(('git', 'push'))} push") or 0)
        assert ship.handoff() == 0
        assert order == ["rebind after 1 push", "arm"]

    def test_a_push_that_landed_and_a_refused_rebind_arm_with_the_refusal(self, ship, tmp_path, monkeypatch):
        """The lane is on origin; the rebind after it refused (gh down, a
        title that did not take). The window is done with the lane: armed,
        the refusal in the marker, and the next window runs `rebind`."""
        _toml(tmp_path, "handoff_push = true\n")
        spawns = _arm(ship, TestHandoffVerb._existing_pr_answers(tmp_path))
        calls = self._arm_calls(ship, monkeypatch)

        def refused_rebind(dry_run=False):
            raise ship.Refused("gh pr edit failed: boom")

        monkeypatch.setattr(ship, "rebind", refused_rebind)
        with pytest.raises(ship.Refused, match="boom"):
            ship.handoff()
        assert spawns.count(("git", "push")) == 1
        assert calls, "the handoff armed nothing after a push that landed"
        held = calls[0]["held"]
        assert held.landed is True and "the push landed" in str(held) and "boom" in str(held)

    def test_a_rebind_that_returns_non_zero_after_the_push_arms_and_refuses(self, ship, tmp_path, monkeypatch):
        """Before DEF-4057 the handoff returned the rebind's code and armed
        nothing, although the push had landed."""
        _toml(tmp_path, "handoff_push = true\n")
        _arm(ship, TestHandoffVerb._existing_pr_answers(tmp_path))
        calls = self._arm_calls(ship, monkeypatch)
        monkeypatch.setattr(ship, "rebind", lambda dry_run=False: 1)
        with pytest.raises(ship.Refused, match="rebind"):
            ship.handoff()
        assert calls, "the handoff armed nothing after a push that landed"
        assert calls[0]["held"].landed is True

    def test_the_opened_pull_request_arms_after_the_open(self, ship, tmp_path, forget_guard, monkeypatch):
        _toml(tmp_path, "handoff_push = true\n")
        _write_guard(tmp_path)
        answers = _open_answers(tmp_path)
        answers[("git", "status", "--porcelain", "-uno")] = (0, "", "")
        answers[_MEMORY_LOG] = (0, "abc1234\n", "")
        answers[_list_key()] = [(0, "[]", ""), (0, "[]", ""), _rows(_pr())]
        spawns = _arm(ship, answers)
        armed_after: list[int] = []
        monkeypatch.setattr(ship, "arm_own_clear_here",
                            lambda root: armed_after.append(len(spawns.calls)) or "own-clear armed (stand-in)")
        assert ship.handoff() == 0
        assert spawns.count(("gh", "pr", "create")) == 1
        assert armed_after and armed_after[0] > spawns.index(("gh", "pr", "create"))

    def test_an_arm_that_raises_does_not_fail_the_landed_handoff(self, ship, tmp_path, monkeypatch, capsys):
        """The push landed; what stops the arm is said with the by-hand reset,
        and the verb exits 0 (a 1 here reads as a failed handoff, which a
        session would run again)."""
        answers = _reads(tmp_path)
        answers[_list_key()] = (0, "[]", "")
        _arm(ship, answers)

        def broken(root):
            raise OSError("read-only state directory")

        monkeypatch.setattr(ship, "arm_own_clear_here", broken)
        assert ship.handoff() == 0
        out = capsys.readouterr().out
        assert "was not armed" in out and "read-only state directory" in out and "/clear by hand" in out

    def test_a_refused_handoff_arms_nothing(self, ship, tmp_path, monkeypatch):
        _toml(tmp_path, "handoff_push = true\n")
        ship._SYNC = _oracle(_two_sessions())
        _arm(ship, TestHandoffVerb._existing_pr_answers(tmp_path))
        order = self._armed(ship, monkeypatch)
        with pytest.raises(ship.Refused, match="2 live sessions work in this checkout"):
            ship.handoff()
        assert order == []

    def test_a_dry_run_arms_nothing_and_says_what_it_would(self, ship, tmp_path, forget_guard, monkeypatch,
                                                           capsys):
        _toml(tmp_path, "handoff_push = true\n")
        _write_guard(tmp_path)
        answers = _open_answers(tmp_path)
        answers[("git", "status", "--porcelain", "-uno")] = (0, "", "")
        answers[_MEMORY_LOG] = (0, "abc1234\n", "")
        answers[_list_key()] = [(0, "[]", ""), (0, "[]", ""), _rows(_pr())]
        spawns = _arm(ship, answers)
        order = self._armed(ship, monkeypatch)
        assert ship.handoff(dry_run=True) == 0
        assert order == [] and spawns.mutations == []
        out = capsys.readouterr().out
        assert "dry-run" in out and "the own-clear marker would be armed" in out

    def test_a_handoff_refused_on_the_red_base_arms_with_the_refusal_then_refuses(
            self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        """DEF-4057's first shape. The row is written and the tree clean; what
        refused the push is the base, not this window, so the marker is armed
        with the refusal for the next window to read, and the refusal still
        stands (the lane stays here, unpushed). Dies to: an arm skipped because
        the push never ran (the unfixed driver), or a push made on the red
        base."""
        spawns = _arm(ship, self._red_base_answers(tmp_path))
        calls = self._arm_calls(ship, monkeypatch)
        with pytest.raises(ship.Refused, match="Nothing lands on a red base"):
            ship.handoff()
        assert calls, "the handoff armed nothing after the red-base refusal"
        assert spawns.mutations == []
        held = calls[0]["held"]
        assert isinstance(held, ship.Held) and held.landed is False
        assert "main red after merge" in str(held)
        assert "own-clear armed" in capsys.readouterr().out

    def test_a_dry_run_on_the_red_base_says_what_it_would_arm_and_arms_nothing(
            self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        spawns = _arm(ship, self._red_base_answers(tmp_path))
        calls = self._arm_calls(ship, monkeypatch)
        with pytest.raises(ship.Refused, match="Nothing lands on a red base"):
            ship.handoff(dry_run=True)
        assert calls == [] and spawns.mutations == []
        assert "dry-run: the own-clear marker would be armed" in capsys.readouterr().out

    def test_a_refusal_the_window_must_fix_arms_nothing(self, ship, tmp_path, monkeypatch):
        """A dirty tree, a lane behind its remote: the handoff is not at its
        end, and a marker here would clear a window with work in it."""
        _toml(tmp_path, "handoff_push = true\n")
        calls = self._arm_calls(ship, monkeypatch)
        answers = TestHandoffVerb._existing_pr_answers(tmp_path)
        answers[("git", "status", "--porcelain", "-uno")] = (0, " M tools/cc/ship.py\n", "")
        _arm(ship, answers)
        with pytest.raises(ship.Refused, match="dirty"):
            ship.handoff()
        answers = TestHandoffVerb._existing_pr_answers(tmp_path)
        answers[("git", "rev-list", "--count")] = (0, "2\n", "")
        spawns = _arm(ship, answers)
        with pytest.raises(ship.Refused, match="does not reach"):
            ship.handoff()
        assert calls == [] and spawns.mutations == []

    def test_a_red_base_with_no_row_is_the_rows_refusal_and_arms_nothing(
            self, ship, tmp_path, forget_guard, monkeypatch):
        """Both reviews, 2026-10-30: the red-base refusal came before the row
        question, so a rowless lane on a red base armed and its window cleared
        with the row unwritten, the tail promising one."""
        answers = self._red_base_answers(tmp_path)
        answers[_MEMORY_LOG] = (0, "", "")   # the lane's commits carry no row
        spawns = _arm(ship, answers)
        calls = self._arm_calls(ship, monkeypatch)
        with pytest.raises(ship.Refused, match="Session Log row"):
            ship.handoff()
        assert calls == [] and spawns.mutations == []

    def test_a_pull_request_that_fails_to_open_after_the_push_arms_with_the_refusal(
            self, ship, tmp_path, forget_guard, monkeypatch):
        """The push landed and `gh pr create` refused: the lane is on origin,
        the next window finishes it, and the refusal names what to run."""
        _toml(tmp_path, "handoff_push = true\n")
        _write_guard(tmp_path)
        answers = _open_answers(tmp_path, create=(1, "", "boom"))
        answers[("git", "status", "--porcelain", "-uno")] = (0, "", "")
        answers[_MEMORY_LOG] = (0, "abc1234\n", "")
        answers[_list_key()] = [(0, "[]", ""), (0, "[]", "")]
        spawns = _arm(ship, answers)
        calls = self._arm_calls(ship, monkeypatch)
        with pytest.raises(ship.Refused, match="boom"):
            ship.handoff()
        assert spawns.count(("git", "push")) == 1
        assert calls, "the handoff armed nothing after a push that landed"
        assert calls[0]["held"].landed is True and "the push landed" in str(calls[0]["held"])

    def test_a_rejected_push_arms_nothing(self, ship, tmp_path, forget_guard, monkeypatch):
        _toml(tmp_path, "handoff_push = true\n")
        _write_guard(tmp_path)
        answers = _open_answers(tmp_path, push=(1, "", "rejected by the remote"))
        answers[("git", "status", "--porcelain", "-uno")] = (0, "", "")
        answers[_MEMORY_LOG] = (0, "abc1234\n", "")
        answers[_list_key()] = [(0, "[]", ""), (0, "[]", "")]
        _arm(ship, answers)
        calls = self._arm_calls(ship, monkeypatch)
        with pytest.raises(ship.Refused, match="rejected by the remote"):
            ship.handoff()
        assert calls == []


class TestTheLaneCarriesItsMemoryRowWhenHandoffPushes:
    """Where the repo opted into handoff pushes, a lane shipped before its
    handoff makes the handoff's row a second push. `open` refuses such a lane
    unless told why; with the setting off, /ship is the push and nothing is
    asked."""

    def _on(self, tmp_path):
        _toml(tmp_path, "handoff_push = true\n")
        _write_guard(tmp_path)

    def test_open_refuses_a_lane_whose_commits_never_touch_the_memory_file(
            self, ship, tmp_path, forget_guard):
        self._on(tmp_path)
        answers = _open_answers(tmp_path)
        answers[_MEMORY_LOG] = (0, "", "")
        spawns = _arm(ship, answers)
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        assert "ESPALIER_MEMORY.md" in str(stop.value) and "--early" in str(stop.value)
        assert spawns.mutations == []

    def test_early_with_a_reason_ships_and_says_why(self, ship, tmp_path, forget_guard, capsys):
        self._on(tmp_path)
        answers = _open_answers(tmp_path)
        answers[_MEMORY_LOG] = (0, "", "")
        spawns = _arm(ship, answers)
        assert ship.open_pr(early="the next lane needs this merge") == 0
        assert spawns.count(("git", "push")) == 1
        assert "the next lane needs this merge" in capsys.readouterr().out
        # on the record, not only on a terminal
        assert any("Shipped before the handoff: the next lane needs this merge" in b
                   for b in spawns.body_texts)

    def test_a_lane_whose_row_is_a_session_log_file_ships_without_early(self, ship, tmp_path, forget_guard):
        """Since 2026-10-10 a handoff writes its row as a file under
        memory/session-log.d/, so a lane can carry its row without touching
        the memory file. Mutation seen red: the memory file read alone, which
        refused every such handoff (review of the Wave C batch)."""
        self._on(tmp_path)
        answers = _open_answers(tmp_path)
        answers[_MEMORY_LOG] = (0, "", "")
        answers[_ROW_FILES] = _row_log(("", ["memory/session-log.d/2026-10-11-120000-win.md"]))
        spawns = _arm(ship, answers)
        assert ship.open_pr() == 0
        assert spawns.count(("git", "push")) == 1

    def test_a_lane_that_adds_only_other_files_is_still_asked(self, ship, tmp_path, forget_guard):
        self._on(tmp_path)
        answers = _open_answers(tmp_path)
        answers[_MEMORY_LOG] = (0, "", "")
        answers[_ROW_FILES] = _row_log()
        _arm(ship, answers)
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        assert "memory/session-log.d/" in str(stop.value)

    def test_a_lane_that_carries_its_row_ships_without_early(self, ship, tmp_path, forget_guard):
        self._on(tmp_path)
        answers = _open_answers(tmp_path)
        answers[_MEMORY_LOG] = (0, "abc1234\n", "")
        spawns = _arm(ship, answers)
        assert ship.open_pr() == 0
        assert spawns.count(_MEMORY_LOG) == 1

    def test_with_handoff_push_off_open_asks_nothing(self, ship, tmp_path, forget_guard):
        _write_guard(tmp_path)
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        assert spawns.count(_MEMORY_LOG) == 0

    def test_preflight_names_the_refusal_to_come(self, ship, tmp_path, capsys):
        _toml(tmp_path, "handoff_push = true\n")
        _memory(tmp_path, "2026-09-30")
        answers = _preflight_answers(tmp_path)
        answers[_MEMORY_LOG] = (0, "", "")
        _arm(ship, answers)
        assert ship.preflight() == 0
        out = capsys.readouterr().out
        assert "ESPALIER_MEMORY.md" in out and "--early" in out


class TestOpenRefusesOnRowDebt:
    """TP-703d 1-D, the second lane (2026-10-30): where handoff_push is on and
    the lane carries no row, --early passes the second-push question but not
    this one. A seat that has shipped ROW_DEBT_CAP lanes since its newest
    Session Log row is refused until a row is committed on the lane (which
    lane_carries_memory_row then reads, and the arm is not asked). The reading
    is TestSeatRowDebt's; here, what open does with it: the fetches before it,
    the comparison at the cap, and no verdict never refusing."""

    _READING = {"machine": "win", "count": 3, "since": "2026-10-18", "where": "base",
                "newest": {"win": ("2026-10-18", "base"), "air": ("2026-10-29", "parked"),
                           "legacy": ("2026-10-10", "pruned")},
                "seats": ["air", "win"]}

    def _on(self, ship, tmp_path, monkeypatch, reading, *, records=(True, ""), machine="win"):
        _toml(tmp_path, "handoff_push = true\n")
        _write_guard(tmp_path)
        seen: list = []
        # Each reading records how many spawns ran before it (the fetches must precede it).
        monkeypatch.setattr(ship, "_row_debt_reading",
                            lambda root, base, prs=None: seen.append((root, base, prs, len(ship.RUN.calls))) or reading)
        monkeypatch.setattr(ship._mail_module(), "fetch_records", lambda root, **kw: records)
        monkeypatch.setattr(ship._mail_module(), "machine_setting",
                            lambda root, **kw: (machine, "stubbed") if machine else (None, "git config espalier.machine is not set"))
        answers = _open_answers(tmp_path)
        answers[_MEMORY_LOG] = (0, "", "")
        return seen, answers

    def test_at_the_cap_early_is_refused_naming_the_count_the_date_the_cap_and_the_way_out(
            self, ship, tmp_path, forget_guard, monkeypatch):
        """Dies to: the comparison flipped (> for >=), the refusal passed by
        --early, a push before the question, or the words without the way out."""
        seen, answers = self._on(ship, tmp_path, monkeypatch, self._READING)
        spawns = _arm(ship, answers)
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr(early="the next lane needs this merge")
        text = str(stop.value)
        assert "has 3 lanes merged on the days after" in text and "2026-10-18" in text
        assert f"the cap is {ship.ROW_DEBT_CAP}" in text and ship.ROW_DEBT_CAP == 3
        assert "_record_fragments.py new session-log" in text and "--early does not pass" in text
        assert "seat name, win" in text and "air 2026-10-29" in text   # a renamed seat finds its rows under the old name
        assert "legacy" not in text   # the first fragments' pseudo-seat has no mail ref and is no seat
        assert seen and seen[0][:2] == (tmp_path, "main") and isinstance(seen[0][2], list)
        assert spawns.mutations == []
        # The base was fetched before the reading (a row merged minutes ago is in the local base).
        fetched = spawns.index(("git", "fetch", "origin", "main"))
        assert 0 <= fetched < seen[0][3], (fetched, seen[0][3])
        pruned = dict(self._READING, where="pruned", since="2026-10-18")
        seen, answers = self._on(ship, tmp_path, monkeypatch, pruned)
        _arm(ship, answers)
        with pytest.raises(ship.Refused, match="pruned from origin/main"):
            ship.open_pr(early="x")

    def test_under_the_cap_early_ships_and_an_unread_debt_ships_with_a_note(
            self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        """Dies to: a None reading refusing (a gh outage would stop every early
        ship), or a debt one under the cap refused."""
        under = dict(self._READING, count=2)
        seen, answers = self._on(ship, tmp_path, monkeypatch, under)
        spawns = _arm(ship, answers)
        assert ship.open_pr(early="the next lane needs this merge") == 0
        assert spawns.count(("git", "push")) == 1 and len(seen) == 1
        assert "unread" not in capsys.readouterr().out
        seen, answers = self._on(ship, tmp_path, monkeypatch, None)
        spawns = _arm(ship, answers)
        assert ship.open_pr(early="the next lane needs this merge") == 0
        assert spawns.count(("git", "push")) == 1
        out = capsys.readouterr().out
        assert "Session Log debt is unread" in out and "--early is taken as given" in out

    def test_a_fetch_that_fails_or_unread_open_pull_requests_read_as_unread_never_a_refusal(
            self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        """The early arm ran before open's base fetch and the fold's records
        fetch, so a row merged forty minutes ago was not in the local base (the
        first lane's failure-mode review). A fetch that fails leaves the debt
        unread: a refusal on a stale base is a refusal on a guess. Dies to: the
        fetch dropped, or its failure read as fresh refs."""
        seen, answers = self._on(ship, tmp_path, monkeypatch, self._READING)
        answers[("git", "fetch", "origin", "main")] = (1, "", "fatal: could not read from remote repository")
        spawns = _arm(ship, answers)
        assert ship.open_pr(early="x") == 0
        out = capsys.readouterr().out
        assert "origin/main could not be fetched" in out and "--early is taken as given" in out and seen == []
        assert spawns.count(("git", "push")) == 1
        seen, answers = self._on(ship, tmp_path, monkeypatch, self._READING, records=(False, "could not reach origin"))
        _arm(ship, answers)
        assert ship.open_pr(early="x") == 0
        assert "records refs could not be fetched (could not reach origin)" in capsys.readouterr().out and seen == []
        seen, answers = self._on(ship, tmp_path, monkeypatch, self._READING)
        answers[("gh", "pr", "list", "--state", "open")] = (1, "", "gh: not logged in")
        _arm(ship, answers)
        assert ship.open_pr(early="x") == 0
        assert "open pull requests could not be read" in capsys.readouterr().out and seen == []
        # A fetch that times out raises in the runner: unread, never a refusal (failure-mode review).
        seen, answers = self._on(ship, tmp_path, monkeypatch, self._READING)
        _arm(ship, answers)
        real_git = ship._git
        slow: list = []

        def slow_git(*a, **k):   # the arm's fetch, the first of the base, times out; open's own later one is quick
            if a[:3] == ("fetch", "origin", "main") and not slow:
                slow.append(a)
                raise ship.Refused("git fetch took longer than 60s")
            return real_git(*a, **k)

        monkeypatch.setattr(ship, "_git", slow_git)
        assert ship.open_pr(early="x") == 0
        assert "could not be fetched (git fetch took longer than 60s)" in capsys.readouterr().out and seen == []
        monkeypatch.setattr(ship, "_git", real_git)
        # An unnamed clone has no seat to read rows for: said by name, never blamed on git or gh.
        seen, answers = self._on(ship, tmp_path, monkeypatch, self._READING, machine=None)
        _arm(ship, answers)
        assert ship.open_pr(early="x") == 0
        assert "names no machine (git config espalier.machine)" in capsys.readouterr().out and seen == []

    def test_the_question_is_asked_only_where_early_is_needed(self, ship, tmp_path, forget_guard, monkeypatch):
        """A lane that carries its row, or a repository with handoff_push off,
        never reads the debt. Dies to: the reading made on every open."""
        seen, answers = self._on(ship, tmp_path, monkeypatch, self._READING)
        answers[_MEMORY_LOG] = (0, "abc1234\n", "")   # the lane carries its row
        _arm(ship, answers)
        assert ship.open_pr() == 0 and seen == []
        _toml(tmp_path, "")
        _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr(early="x") == 0 and seen == []

    def test_the_second_push_message_names_the_cap(self, ship, tmp_path, forget_guard, monkeypatch):
        seen, answers = self._on(ship, tmp_path, monkeypatch, self._READING)
        _arm(ship, answers)
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        assert f"past {ship.ROW_DEBT_CAP} lanes" in str(stop.value) and "--early" in str(stop.value) and seen == []


class _FakeMail:
    """The channel's park, recorded; ``refuse`` makes it refuse as an unnamed seat does."""

    class Unresolvable(Exception):
        pass

    def __init__(self, refuse: str | None = None):
        self.parked: list[tuple[str, object, str, object]] = []
        self.refuse = refuse

    def park(self, root, path, data, base_ref, *, from_rev=None, say=print, **_kw):
        if self.refuse:
            raise self.Unresolvable(self.refuse)
        self.parked.append((path, data, base_ref, from_rev))
        say(f"parked {path}")
        return "c0ffee"


_PARKED_ROW = "memory/session-log.d/2026-10-16-010101-win.md"


class TestTheSessionLogFoldAndPark:
    """DEF-5007. A lane's push folds the parked rows in and prunes to the cap,
    before the marker's sha (the fold's commits are the head the marker binds);
    a handoff whose lane carries only its row parks it instead of opening a pull
    request for one row; the rows a fold adds are no row of this lane."""

    def test_open_folds_before_the_marker_is_bound_and_the_push(self, ship, tmp_path, forget_guard):
        """Dies to: no fold (the cap's one writer gone), or a fold after the
        sha the marker binds, which binds the marker to a head the push moves."""
        _write_guard(tmp_path)
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        [fold] = ship.FOLDS
        assert fold["base"] == "main" and fold["dry_run"] is False
        assert fold["at"] < spawns.index(("git", "push"))
        heads = [i for i, c in enumerate(spawns.calls) if c[:3] == ["git", "rev-parse", "HEAD"]]
        assert any(i >= fold["at"] for i in heads), (fold, heads)

    def test_the_handoffs_push_onto_an_open_pull_request_folds_first(self, ship, tmp_path, monkeypatch):
        _toml(tmp_path, "handoff_push = true\n")
        answers = TestHandoffVerb._existing_pr_answers(tmp_path)
        spawns = _arm(ship, answers)
        monkeypatch.setattr(ship, "rebind", lambda **_kw: 0)
        assert ship.handoff() == 0
        [fold] = ship.FOLDS
        assert fold["at"] < spawns.index(("git", "push"))

    def _handoff_only(self, ship, tmp_path, diff: str, mail: _FakeMail):
        _toml(tmp_path, "handoff_push = true\n")
        (tmp_path / _PARKED_ROW).parent.mkdir(parents=True)
        (tmp_path / _PARKED_ROW).write_bytes(b"| 2026-10-16 | the row | -- |\n")
        answers = _reads(tmp_path)
        answers[_list_key()] = (0, "[]", "")
        answers[("git", "status", "--porcelain", "-uno")] = (0, "", "")
        answers[("git", "fetch")] = (0, "", "")
        answers[_LANE_DIFF] = (0, diff, "")
        answers[("git", "rev-parse", "HEAD")] = (0, f"{HEAD}\n", "")
        answers[("git", "merge-base")] = (0, f"{OLD_HEAD}\n", "")
        answers[("git", "reset", "--keep")] = (0, "", "")
        ship._MAIL = mail
        return _arm(ship, answers)

    def test_a_lane_carrying_only_its_row_parks_it_and_opens_nothing(self, ship, tmp_path, monkeypatch, capsys):
        """The assign's red: dies to a pull request opened for one row (seven
        in two days, #212 to #240)."""
        mail = _FakeMail()
        spawns = self._handoff_only(ship, tmp_path, f"A\t{_PARKED_ROW}\n", mail)
        monkeypatch.setattr(ship, "open_pr", lambda **_kw: pytest.fail("a pull request opened for the row alone"))
        assert ship.handoff() == 0
        assert mail.parked == [(_PARKED_ROW, None, "origin/main", "HEAD")]   # the committed blob, not the file
        assert spawns.count(("git", "push")) == 0 and spawns.count(("gh", "pr", "create")) == 0
        # Both reviews' BLOCKER: the row's commit is dropped from the branch once parked.
        [reset] = spawns.matching(("git", "reset", "--keep"))
        assert reset[-1] == OLD_HEAD, reset
        out = capsys.readouterr().out
        assert "No pull request opened" in out and "next lane's push" in out and out.isascii()
        assert f"moved back to {OLD_HEAD[:7]}" in out and HEAD[:7] in out

    def test_a_lane_that_edits_a_row_opens_as_before(self, ship, tmp_path, monkeypatch):
        """Dies to: an edited row passing the rows-only test and parking the new
        row alone, so the edit never reached a pull request (code review,
        driven)."""
        mail = _FakeMail()
        self._handoff_only(ship, tmp_path, f"M\tmemory/session-log.d/2026-10-13-120000-win.md\nA\t{_PARKED_ROW}\n",
                           mail)
        opened: list[str] = []
        monkeypatch.setattr(ship, "open_pr", lambda **_kw: opened.append("open") or 0)
        assert ship.handoff() == 0
        assert opened == ["open"] and mail.parked == []

    def test_the_fold_verb_folds_against_the_default_branch(self, ship, tmp_path):
        """A direct-push tree's /handoff step: the same writer, at its own push."""
        answers = _reads(tmp_path, branch="main")
        answers[("git", "fetch")] = (0, "", "")
        _arm(ship, answers)
        assert ship.main(["fold"]) == 0
        assert [f["base"] for f in ship.FOLDS] == ["main"]

    def test_a_seat_the_channel_refuses_opens_a_pull_request_as_before(self, ship, tmp_path, monkeypatch, capsys):
        """Dies to: the row stranded on a branch where the seat has no name."""
        mail = _FakeMail(refuse="this clone names no machine")
        self._handoff_only(ship, tmp_path, f"A\t{_PARKED_ROW}\n", mail)
        opened: list[str] = []
        monkeypatch.setattr(ship, "open_pr", lambda **_kw: opened.append("open") or 0)
        assert ship.handoff() == 0
        assert opened == ["open"] and mail.parked == []
        assert "names no machine" in capsys.readouterr().out

    def test_a_lane_with_code_beside_its_row_opens_as_before(self, ship, tmp_path, monkeypatch):
        """Dies to: a lane's code parked away with its row, never reaching a pull request."""
        mail = _FakeMail()
        self._handoff_only(ship, tmp_path, f"A\t{_PARKED_ROW}\nM\ttools/cc/ship.py\n", mail)
        opened: list[str] = []
        monkeypatch.setattr(ship, "open_pr", lambda **_kw: opened.append("open") or 0)
        assert ship.handoff() == 0
        assert opened == ["open"] and mail.parked == []

    def test_a_dry_run_says_it_would_park_and_parks_nothing(self, ship, tmp_path, capsys):
        mail = _FakeMail()
        spawns = self._handoff_only(ship, tmp_path, f"A\t{_PARKED_ROW}\n", mail)
        assert ship.handoff(dry_run=True) == 0
        assert mail.parked == [] and spawns.mutations == []
        assert f"dry-run: park {_PARKED_ROW}" in capsys.readouterr().out

    def test_rows_a_fold_added_are_no_row_of_this_lane(self, ship, tmp_path, forget_guard):
        """Dies to: another seat's parked row, folded in, read as this lane's
        row, so a lane shipped before its handoff is not asked for --early."""
        _toml(tmp_path, "handoff_push = true\n")
        _write_guard(tmp_path)
        assert ship._fragments_module().FOLD_TRAILER == f"Espalier-Fold: {_FOLD}"
        answers = _open_answers(tmp_path)
        answers[_MEMORY_LOG] = (0, "", "")
        answers[_ROW_FILES] = _row_log((_FOLD, ["memory/session-log.d/2026-10-16-090000-mac.md"]))
        _arm(ship, answers)
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        assert "--early" in str(stop.value)

    def test_the_lanes_own_row_beside_a_fold_still_counts(self, ship, tmp_path, forget_guard):
        """Air 847e2b: only the fold's rows are skipped."""
        _toml(tmp_path, "handoff_push = true\n")
        _write_guard(tmp_path)
        answers = _open_answers(tmp_path)
        answers[_MEMORY_LOG] = (0, "", "")
        answers[_ROW_FILES] = _row_log(
            (_FOLD, ["memory/session-log.d/2026-10-16-090000-mac.md"]),
            ("", ["memory/session-log.d/2026-10-16-080000-win.md"]))
        spawns = _arm(ship, answers)
        assert ship.open_pr() == 0
        assert spawns.count(("git", "push")) == 1


class TestPushClaimsInShippedBodiesNameTheSetting:
    """Review, 2026-10-03: with the default flipped to off, the shipped /commit
    body still told adopters "the lane ships once, at /handoff". A paragraph of a
    deployed command body that says the handoff pushes must name handoff_push,
    the setting the claim now depends on."""

    _CLAIM_RE = re.compile(r"ships \*{0,2}once|pushes the lane|step 8's push|lane's ONE push", re.I)

    @classmethod
    def bare_claims(cls, bodies: list[tuple[str, str]]) -> list[str]:
        bare = []
        for name, text in bodies:
            for para in text.split("\n\n"):
                if cls._CLAIM_RE.search(para) and "handoff_push" not in para:
                    bare.append(f"{name}: {para.strip()[:90]}")
        return bare

    @pytest.mark.contract
    def test_every_handoff_push_claim_names_the_setting(self):
        paths = visible(checkout_glob(ROOT / "espalier" / "assets" / "claude" / "commands", "*.md"), ROOT / "espalier" / "assets" / "claude" / "commands")
        assert len(paths) >= 10, "the deployed command bodies were not found"
        bodies = [(p.name, p.read_text(encoding="utf-8")) for p in paths]
        assert self.bare_claims(bodies) == []

    def test_the_check_reds_on_the_sentence_that_motivated_it(self):
        old = ("After a clean commit, say that the lane ships **once, at `/handoff`**: the\n"
               "handoff writes its row, commits, and runs the ship driver as its last step.")
        assert self.bare_claims([("commit.md", old)]) != []


class TestTheTempFileIsWrittenWithoutNewlineTranslation:
    def test_open_pr_opens_its_temp_file_with_newline_empty(self):
        """Host-independent pin for the half of the CRLF fix a Linux CI cell
        cannot see: text mode translates nothing where os.linesep is a line
        feed, so dropping newline="" stays green on every required cell and
        re-ships the doubling on Windows. Asserted on the one
        NamedTemporaryFile call inside open_pr, by AST."""
        tree = ast.parse(SHIP.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "open_pr")
        calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
                 and isinstance(c.func, ast.Attribute) and c.func.attr == "NamedTemporaryFile"]
        assert len(calls) == 1, "open_pr writes exactly one temp file"
        kw = {k.arg: k.value for k in calls[0].keywords}
        assert "newline" in kw and isinstance(kw["newline"], ast.Constant) and kw["newline"].value == "", (
            "open_pr's temp file must be opened with newline=\"\": the interpreter otherwise "
            "turns each line feed into os.linesep, and on Windows the body reaches gh doubled")

    def test_the_body_is_folded_through_the_one_owner(self):
        """The fold has one owner (`_json_safe.fold_newlines`); open_pr calls it
        rather than spelling a fourth in-tree replace chain."""
        tree = ast.parse(SHIP.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "open_pr")
        assert any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "fold_newlines"
                   for c in ast.walk(fn)), "open_pr folds the body through fold_newlines"


class TestTheMemoryFileIsReadLikeAnyOperatorWrittenRecord:
    def test_a_cp1252_memory_file_is_a_named_problem_not_a_traceback(self, ship, tmp_path):
        (tmp_path / "ESPALIER_MEMORY.md").write_bytes(
            "| 2026-10-01 | the lane\u2019s story |\n".encode("cp1252"))
        problem = ship.memory_problem(tmp_path)
        assert problem.startswith("ESPALIER_MEMORY.md: ") and "not UTF-8 text" in problem

    def test_a_utf16_memory_file_with_a_mark_still_answers(self, ship, tmp_path):
        (tmp_path / "ESPALIER_MEMORY.md").write_bytes(
            "| 2026-10-01 | a row |\n".encode("utf-16"))
        assert ship.memory_problem(tmp_path) == ""

    def test_an_absent_memory_file_is_no_problem(self, ship, tmp_path):
        assert ship.memory_problem(tmp_path) == ""

    def test_the_push_lands_before_the_pull_request_is_created(
            self, ship, tmp_path, forget_guard):
        _write_guard(tmp_path)
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        assert 0 <= spawns.index(("git", "push")) < spawns.index(("gh", "pr", "create"))

    def test_auto_merge_is_armed_and_read_back(self, ship, tmp_path, forget_guard, capsys):
        _write_guard(tmp_path)
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        armed = spawns.index(("gh", "pr", "merge"))
        read_back = spawns.index(("gh", "pr", "view"))
        assert 0 <= armed < read_back
        assert spawns.matching(("gh", "pr", "merge"))[0] == ["gh", "pr", "merge", "7", "--auto", "--merge"]
        assert "#7 open, auto-merge armed, one push" in capsys.readouterr().out

    def test_an_unprotected_diff_binds_nothing(self, ship, tmp_path, forget_guard):
        _write_guard(tmp_path)
        spawns = _arm(ship, _open_answers(tmp_path, diff="README.md\n"))
        assert ship.open_pr() == 0
        created = spawns.matching(("gh", "pr", "create"))[0]
        assert created[created.index("--title") + 1] == "feat: a thing"
        assert MARKER not in " ".join(created)

    def test_a_tree_with_no_harness_guard_binds_nothing_and_says_so(
            self, ship, tmp_path, capsys):
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        created = spawns.matching(("gh", "pr", "create"))[0]
        assert MARKER not in " ".join(created)
        assert "no harness guard on this tree" in capsys.readouterr().out

    def test_a_guard_that_will_not_load_binds_the_marker_and_says_why(
            self, ship, tmp_path, forget_guard, capsys):
        _write_guard(tmp_path, 'raise RuntimeError("the guard is broken")\n')
        predicate = ship.guard_predicate(tmp_path)
        assert predicate is not None
        assert predicate("README.md") is True
        out = capsys.readouterr().out
        assert "could not be loaded" in out
        assert "binding the marker anyway" in out

    def test_a_guard_without_the_predicate_binds_the_marker_and_says_why(
            self, ship, tmp_path, forget_guard, capsys):
        _write_guard(tmp_path, "VERSION = 1\n")
        predicate = ship.guard_predicate(tmp_path)
        assert predicate is not None
        assert predicate("README.md") is True
        assert "no is_protected" in capsys.readouterr().out

    def test_the_real_guard_binds_the_marker_for_a_workflow_path(self, ship, tmp_path, forget_guard):
        """DEC-39 (b) scopes the workflows prefix to the self-host posture,
        and this driver calls the guard's predicate with one argument, never
        through its ``run()``: the one-argument answer must stay the tight
        one, or a workflow-only lane on the harness's own repository ships
        with no marker and its required check reds. On an adopter the same
        call over-binds, which costs nothing."""
        _write_guard(tmp_path, (ROOT / "tools" / "cc" / "ci_guard.py").read_text(encoding="utf-8"))
        predicate = ship.guard_predicate(tmp_path)
        assert predicate is not None
        assert predicate(".github/workflows/release.yml") is True
        assert predicate(".github/workflows/harness-guard.yml") is True
        assert predicate("README.md") is False

    def test_dry_run_pushes_nothing_and_creates_nothing(self, ship, tmp_path, capsys):
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr(dry_run=True) == 0
        assert spawns.mutations == []
        assert "dry-run" in capsys.readouterr().out

    def test_the_default_branch_takes_no_push(self, ship, tmp_path):
        spawns = _arm(ship, _open_answers(tmp_path, branch="main"))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        assert "run `lane` first" in str(stop.value)
        assert spawns.mutations == []

    def test_an_open_pull_request_already_on_the_lane_is_refused(self, ship, tmp_path):
        spawns = _arm(ship, _open_answers(tmp_path, existing=json.dumps([_pr()])))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        assert "an open pull request already exists" in str(stop.value)
        assert spawns.mutations == []

    def test_commits_on_the_remote_this_head_does_not_reach_are_refused(
            self, ship, tmp_path):
        spawns = _arm(ship, _open_answers(tmp_path, behind="2\n"))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        assert "2 commit(s) this HEAD does not reach" in str(stop.value)
        assert "never rebase or force-push" in str(stop.value)
        assert spawns.mutations == []

    def test_a_rejected_push_stops_before_the_pull_request_is_created(
            self, ship, tmp_path):
        spawns = _arm(ship, _open_answers(tmp_path, push=(1, "", "non-fast-forward")))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        assert "the push was rejected" in str(stop.value)
        assert spawns.count(("gh", "pr", "create")) == 0

    def test_a_diff_that_lists_no_paths_is_refused_before_the_create(
            self, ship, tmp_path, forget_guard):
        _write_guard(tmp_path)
        spawns = _arm(ship, _open_answers(tmp_path, diff="\n"))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        assert "listed no paths" in str(stop.value)
        assert spawns.count(("gh", "pr", "create")) == 0

    def test_a_failed_create_stops_before_auto_merge(self, ship, tmp_path, forget_guard):
        _write_guard(tmp_path)
        spawns = _arm(ship, _open_answers(tmp_path, create=(1, "", "no commits between")))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        assert "gh pr create failed" in str(stop.value)
        assert spawns.count(("gh", "pr", "merge")) == 0

    def test_auto_merge_that_does_not_arm_is_refused_with_the_url(
            self, ship, tmp_path, forget_guard):
        _write_guard(tmp_path)
        _arm(ship, _open_answers(tmp_path, merge=(1, "", "not allowed")))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        assert "auto-merge did not arm for #7" in str(stop.value)
        assert "https://example.invalid/pull/7" in str(stop.value)

    def test_auto_merge_that_reads_back_unarmed_is_refused(
            self, ship, tmp_path, forget_guard):
        _write_guard(tmp_path)
        _arm(ship, _open_answers(tmp_path, armed='{"autoMergeRequest": null}'))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        assert "reads back as NOT armed" in str(stop.value)

    def test_a_diff_that_fails_is_refused_before_the_create(
            self, ship, tmp_path, forget_guard):
        _write_guard(tmp_path)
        answers = _open_answers(tmp_path)
        answers[("git", "diff", "--name-only")] = (128, "", "bad revision")
        spawns = _arm(ship, answers)
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        assert "git diff against origin/main failed" in str(stop.value)
        assert spawns.count(("gh", "pr", "create")) == 0


# ── rebind ───────────────────────────────────────────────────────────────────

def _rebind_answers(root, *, branch="lane/x", title=f"feat: a thing {MARKER}@0000000",
                    head=HEAD, edit=(0, "", ""), after=None, runs=None) -> dict:
    answers = _reads(root, branch=branch)
    answers.update({
        _list_key(branch): _rows(_pr(title=title, head=head)),
        ("git", "rev-parse", "HEAD"): (0, f"{HEAD}\n", ""),
        ("gh", "pr", "edit"): edit,
        ("gh", "pr", "view"): (0, json.dumps(
            {"title": after if after is not None else f"feat: a thing {MARKER}@{SHORT}"}), ""),
        ("gh", "run", "list"): runs or [
            (0, json.dumps([{"headSha": HEAD, "databaseId": 99}]), ""),           # before the strip: the push's own run
            (0, json.dumps([{"headSha": HEAD, "databaseId": 99}, {"headSha": HEAD, "databaseId": 100}]), ""),  # the strip edit's run
        ],
    })
    return answers


def _live_gate(root: Path, *, live: bool = True, parked: bool = False) -> None:
    """A harness-guard workflow on the tree: one that reads the title live (the
    named step present) or an older one that judges the event payload's title,
    with or without a newer copy parked beside it."""
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    body = "name: Harness Guard\njobs:\n  verify:\n    steps:\n"
    if live:
        body += "      - name: Read the pull request title as it is now\n"
    body += "      - name: Check protected paths\n"
    (wf / "harness-guard.yml").write_text(body, encoding="utf-8")
    if parked:
        (wf / "harness-guard.yml.new").write_text(body, encoding="utf-8")


class TestRebind:
    def test_a_stale_binding_takes_exactly_one_edit_carrying_exactly_one_marker(
            self, ship, tmp_path, monkeypatch, capsys):
        _bind_clock(ship, monkeypatch)
        spawns = _arm(ship, _rebind_answers(tmp_path))
        assert ship.rebind() == 0
        edits = spawns.matching(("gh", "pr", "edit"))
        assert len(edits) == 1
        title = edits[0][edits[0].index("--title") + 1]
        assert title == f"feat: a thing {MARKER}@{SHORT}"
        assert title.count(MARKER) == 1
        assert spawns.count(("gh", "run", "list")) == 0
        assert f"#7 re-bound to {SHORT}" in capsys.readouterr().out

    def test_a_title_already_bound_is_stripped_then_re_bound_with_a_new_run_between(
            self, ship, tmp_path, monkeypatch, capsys):
        """The push's own run already sits on this head, so "a run on the head"
        is satisfied at once and proves nothing: the wait is for a run that was
        not there before the strip edit (the known set is read before it)."""
        _bind_clock(ship, monkeypatch)
        _live_gate(tmp_path)
        bound = f"feat: a thing {MARKER}@{SHORT}"
        spawns = _arm(ship, _rebind_answers(tmp_path, title=bound))
        assert ship.rebind() == 0
        edits = spawns.matching(("gh", "pr", "edit"))
        assert len(edits) == 2
        first = edits[0][edits[0].index("--title") + 1]
        second = edits[1][edits[1].index("--title") + 1]
        assert MARKER not in first
        assert second == bound
        lists = [i for i, c in enumerate(spawns.calls) if tuple(c[:3]) == ("gh", "run", "list")]
        e0, e1 = spawns.calls.index(edits[0]), spawns.calls.index(edits[1])
        assert lists[0] < e0 < lists[-1] < e1, "known runs read before the strip; a new run seen before the re-bind"
        assert len(lists) == 2, "the first poll after the strip already sees the new run"
        assert "re-firing the check" in capsys.readouterr().out

    def test_a_wait_is_not_satisfied_by_the_run_that_was_already_there(
            self, ship, tmp_path, monkeypatch, capsys):
        """Dies to a wait keyed on the head sha: the push's run matches at once."""
        clock = _bind_clock(ship, monkeypatch)
        _live_gate(tmp_path)
        bound = f"feat: a thing {MARKER}@{SHORT}"
        same = (0, json.dumps([{"headSha": HEAD, "databaseId": 99}]), "")
        spawns = _arm(ship, _rebind_answers(tmp_path, title=bound, runs=same))
        assert ship.rebind() == 0
        assert clock.now >= ship.RUN_WAIT_SECONDS, "the wait ran to its ceiling: the old run never counted"
        assert spawns.count(("gh", "pr", "edit")) == 2
        assert "no new harness-guard run appeared" in capsys.readouterr().out

    def test_an_already_bound_title_on_a_payload_reading_gate_edits_nothing_and_says_why(
            self, ship, tmp_path, monkeypatch, capsys):
        """On an older workflow the marker-less title could be the one the
        surviving run judges -- the stall this verb exists to clear. So it
        edits nothing there and names the re-run, and the parked newer copy."""
        _bind_clock(ship, monkeypatch)
        bound = f"feat: a thing {MARKER}@{SHORT}"
        _live_gate(tmp_path, live=False)
        spawns = _arm(ship, _rebind_answers(tmp_path, title=bound))
        assert ship.rebind() == 0
        assert spawns.count(("gh", "pr", "edit")) == 0
        out = capsys.readouterr().out
        assert "judges the event payload" in out and "harness-guard.yml.new" not in out
        _live_gate(tmp_path, live=False, parked=True)
        spawns = _arm(ship, _rebind_answers(tmp_path, title=bound))
        assert ship.rebind() == 0
        assert spawns.count(("gh", "pr", "edit")) == 0
        assert "harness-guard.yml.new" in capsys.readouterr().out

    def test_a_branch_with_no_open_pull_request_is_refused_before_any_edit(
            self, ship, tmp_path, monkeypatch):
        _bind_clock(ship, monkeypatch)
        answers = _rebind_answers(tmp_path)
        answers[_list_key()] = (0, "[]", "")
        spawns = _arm(ship, answers)
        with pytest.raises(ship.Refused) as stop:
            ship.rebind()
        assert "no open pull request for lane/x" in str(stop.value)
        assert spawns.mutations == []

    def test_a_head_the_pull_request_has_not_seen_is_refused_before_any_edit(
            self, ship, tmp_path, monkeypatch):
        _bind_clock(ship, monkeypatch)
        spawns = _arm(ship, _rebind_answers(tmp_path, head=OLD_HEAD))
        with pytest.raises(ship.Refused) as stop:
            ship.rebind()
        assert "push first" in str(stop.value)
        assert spawns.mutations == []

    def test_a_failed_edit_is_refused(self, ship, tmp_path, monkeypatch):
        _bind_clock(ship, monkeypatch)
        _arm(ship, _rebind_answers(tmp_path, edit=(1, "", "could not update")))
        with pytest.raises(ship.Refused) as stop:
            ship.rebind()
        assert "gh pr edit failed" in str(stop.value)

    def test_a_title_that_did_not_take_the_binding_is_refused(
            self, ship, tmp_path, monkeypatch):
        _bind_clock(ship, monkeypatch)
        _arm(ship, _rebind_answers(tmp_path, after="feat: a thing"))
        with pytest.raises(ship.Refused) as stop:
            ship.rebind()
        assert "did not take the binding" in str(stop.value)

    def test_dry_run_edits_nothing(self, ship, tmp_path, monkeypatch, capsys):
        _bind_clock(ship, monkeypatch)
        spawns = _arm(ship, _rebind_answers(tmp_path))
        assert ship.rebind(dry_run=True) == 0
        assert spawns.mutations == []
        assert "dry-run" in capsys.readouterr().out

    def test_a_wait_that_ends_without_a_run_says_so_and_re_binds_anyway(
            self, ship, tmp_path, monkeypatch, capsys):
        _bind_clock(ship, monkeypatch)
        bound = f"feat: a thing {MARKER}@{SHORT}"
        _live_gate(tmp_path)
        spawns = _arm(ship, _rebind_answers(tmp_path, title=bound, runs=(0, "[]", "")))
        assert ship.rebind() == 0
        assert "no new harness-guard run appeared" in capsys.readouterr().out
        assert spawns.count(("gh", "pr", "edit")) == 2

    def test_a_head_git_cannot_name_is_refused_before_any_edit(
            self, ship, tmp_path, monkeypatch):
        _bind_clock(ship, monkeypatch)
        answers = _rebind_answers(tmp_path)
        answers[("git", "rev-parse", "HEAD")] = (128, "", "unknown revision")
        spawns = _arm(ship, answers)
        with pytest.raises(ship.Refused) as stop:
            ship.rebind()
        assert "git could not name HEAD" in str(stop.value)
        assert spawns.mutations == []

    def test_a_failed_strip_edit_is_refused_before_the_re_bind(
            self, ship, tmp_path, monkeypatch):
        _bind_clock(ship, monkeypatch)
        bound = f"feat: a thing {MARKER}@{SHORT}"
        spawns = _arm(ship, _rebind_answers(
            tmp_path, title=bound, edit=[(1, "", "could not update"), (0, "", "")]))
        with pytest.raises(ship.Refused) as stop:
            ship.rebind()
        assert "gh pr edit failed" in str(stop.value)
        assert spawns.count(("gh", "pr", "edit")) == 1
        assert spawns.count(("gh", "run", "list")) == 1, "the known set is read before the strip; no wait ran"


# ── catch-up ─────────────────────────────────────────────────────────────────

def _catch_up_answers(root, *, branch="lane/x", update=(0, "", ""), heads=None,
                      pull=(0, "", "")) -> dict:
    answers = _rebind_answers(root, branch=branch)
    answers[_list_key(branch)] = heads or [
        _rows(_pr(head=OLD_HEAD, title=f"feat: a thing {MARKER}@0000000")),
        _rows(_pr(head=HEAD, title=f"feat: a thing {MARKER}@0000000")),
    ]
    answers[("gh", "pr", "update-branch")] = update
    answers[("git", "pull")] = pull
    return answers


class TestCatchUp:
    def test_the_head_moves_then_the_lane_is_pulled_and_re_bound(
            self, ship, tmp_path, monkeypatch):
        _bind_clock(ship, monkeypatch)
        spawns = _arm(ship, _catch_up_answers(tmp_path))
        assert ship.catch_up() == 0
        pulled = spawns.index(("git", "pull"))
        edited = spawns.index(("gh", "pr", "edit"))
        assert 0 <= pulled < edited
        assert spawns.count(("gh", "pr", "edit")) == 1

    def test_a_pull_request_that_is_not_behind_says_so_and_pulls_nothing(
            self, ship, tmp_path, monkeypatch, capsys):
        _bind_clock(ship, monkeypatch)
        spawns = _arm(ship, _catch_up_answers(
            tmp_path, update=(1, "", "already up to date with the base branch")))
        assert ship.catch_up() == 0
        assert "is not behind its base" in capsys.readouterr().out
        assert spawns.count(("git", "pull")) == 0

    def test_an_update_branch_verb_that_fails_is_refused_before_the_pull(
            self, ship, tmp_path, monkeypatch):
        _bind_clock(ship, monkeypatch)
        spawns = _arm(ship, _catch_up_answers(
            tmp_path, update=(1, "", "unknown command update-branch")))
        with pytest.raises(ship.Refused) as stop:
            ship.catch_up()
        assert "gh pr update-branch failed" in str(stop.value)
        assert spawns.count(("git", "pull")) == 0

    def test_a_head_that_never_moves_is_refused_before_the_pull(
            self, ship, tmp_path, monkeypatch):
        _bind_clock(ship, monkeypatch)
        stuck = _rows(_pr(head=OLD_HEAD, title=f"feat: a thing {MARKER}@0000000"))
        spawns = _arm(ship, _catch_up_answers(tmp_path, heads=[stuck]))
        with pytest.raises(ship.Refused) as stop:
            ship.catch_up()
        assert "head did not move" in str(stop.value)
        assert spawns.count(("git", "pull")) == 0

    def test_a_lane_that_cannot_fast_forward_is_refused_before_any_rebind(
            self, ship, tmp_path, monkeypatch):
        _bind_clock(ship, monkeypatch)
        spawns = _arm(ship, _catch_up_answers(
            tmp_path, pull=(1, "", "not possible to fast-forward")))
        with pytest.raises(ship.Refused) as stop:
            ship.catch_up()
        assert "cannot fast-forward lane/x" in str(stop.value)
        assert spawns.count(("gh", "pr", "edit")) == 0


# ── the merge-first path: open, the handoff's push, catch-up ─────────────────

#: What `git merge-tree --write-tree --name-only` prints for a lane that would
#: conflict on the memory row: the tree it wrote, the conflicted paths, a blank,
#: then the informational lines.
_CONFLICT_ON_MEMORY = (1, "abc123\nESPALIER_MEMORY.md\n\nAuto-merging ESPALIER_MEMORY.md\nCONFLICT (content)\n", "")
_CANNOT_PROBE = (129, "", "error: unknown option `write-tree'")


def _stub_resolver(ship, monkeypatch, spawns, *, refuses: str | None = None, merged: bool = True) -> list[dict]:
    """Stand in for record_merge.merge_ref_in (its own tests drive it against
    real git): record what the driver handed it and when, then answer."""
    calls: list[dict] = []

    def fake(root, ref, *, run, say):
        calls.append({"root": root, "ref": ref, "run": run, "spawns_before": len(spawns.calls)})
        if refuses:
            raise ship.record_merge.Unresolvable(refuses)
        say(f"merged {ref}; resolved by shape: ESPALIER_MEMORY.md")
        return ship.record_merge.MergeReport(merged, ["ESPALIER_MEMORY.md"], [])

    monkeypatch.setattr(ship.record_merge, "merge_ref_in", fake)
    return calls


class TestPrePushMerge:
    """`open` and the handoff's push merge the base in FIRST when the lane
    would conflict, with the record files resolved by shape, so the pull
    request is born mergeable and the merge rides the one push. Measured
    2026-10-05: three lanes in one day read CONFLICTING on the memory row and
    the ledger's counts, which GitHub's own merge cannot resolve (it honours no
    merge driver), and each was resolved by hand."""

    def test_a_conflicting_lane_is_merged_before_the_sha_is_read_and_before_the_push(
            self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        _write_guard(tmp_path)
        answers = _open_answers(tmp_path)
        answers[("git", "merge-tree")] = _CONFLICT_ON_MEMORY
        answers[("git", "status", "--porcelain", "-uno")] = (0, "", "")
        spawns = _arm(ship, answers)
        calls = _stub_resolver(ship, monkeypatch, spawns)
        assert ship.open_pr() == 0
        assert len(calls) == 1 and calls[0]["ref"] == "origin/main" and calls[0]["run"] is spawns
        assert calls[0]["spawns_before"] <= spawns.index(("git", "rev-parse", "HEAD")), \
            "the marker's sha is read after the merge, or it binds a head the merge moved"
        assert calls[0]["spawns_before"] <= spawns.index(("git", "push"))
        assert spawns.count(("git", "push")) == 1
        assert "resolved by shape: ESPALIER_MEMORY.md" in capsys.readouterr().out

    def test_a_conflict_the_resolver_refuses_is_a_note_and_the_lane_ships_dirty_as_before(
            self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        _write_guard(tmp_path)
        answers = _open_answers(tmp_path)
        answers[("git", "merge-tree")] = _CONFLICT_ON_MEMORY
        answers[("git", "status", "--porcelain", "-uno")] = (0, "", "")
        spawns = _arm(ship, answers)
        _stub_resolver(ship, monkeypatch, spawns, refuses="conflicts outside the record files: README.md")
        assert ship.open_pr() == 0
        assert spawns.count(("git", "push")) == 1
        out = capsys.readouterr().out
        assert "will read DIRTY" in out and "README.md" in out and "git merge origin/main" in out

    def test_a_dirty_tree_with_a_conflict_is_refused_before_the_merge_and_the_push(
            self, ship, tmp_path, forget_guard, monkeypatch):
        _write_guard(tmp_path)
        answers = _open_answers(tmp_path)
        answers[("git", "merge-tree")] = _CONFLICT_ON_MEMORY
        answers[("git", "status", "--porcelain", "-uno")] = (0, " M tools/cc/ship.py\n", "")
        spawns = _arm(ship, answers)
        calls = _stub_resolver(ship, monkeypatch, spawns)
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        assert "the tracked tree is dirty" in str(stop.value)
        assert calls == [] and spawns.mutations == []

    def test_a_git_that_cannot_probe_notes_it_and_ships(self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        _write_guard(tmp_path)
        answers = _open_answers(tmp_path)
        answers[("git", "merge-tree")] = _CANNOT_PROBE
        spawns = _arm(ship, answers)
        calls = _stub_resolver(ship, monkeypatch, spawns)
        assert ship.open_pr() == 0
        assert calls == [] and spawns.count(("git", "push")) == 1
        assert "could not probe the merge" in capsys.readouterr().out

    def test_dry_run_names_the_merge_it_would_make_and_makes_no_merge_and_no_push(
            self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        _write_guard(tmp_path)
        answers = _open_answers(tmp_path)
        answers[("git", "merge-tree")] = _CONFLICT_ON_MEMORY
        spawns = _arm(ship, answers)
        calls = _stub_resolver(ship, monkeypatch, spawns)
        assert ship.open_pr(dry_run=True) == 0
        assert calls == [] and spawns.mutations == []
        assert "would merge origin/main into the lane first (conflicts on ESPALIER_MEMORY.md)" in capsys.readouterr().out

    def test_the_title_and_body_are_the_lanes_not_the_merge_commits(
            self, ship, tmp_path, forget_guard, monkeypatch):
        """Both reviews, driven: after a real merge `git log -1` is the merge
        commit's subject, and the first cut read the title after the merge, so
        every conflicting lane opened as "Merge remote-tracking branch ..." with
        the marker bound to it."""
        _write_guard(tmp_path)
        answers = _open_answers(tmp_path)
        answers[("git", "merge-tree")] = _CONFLICT_ON_MEMORY
        answers[("git", "status", "--porcelain", "-uno")] = (0, "", "")
        spawns = _arm(ship, answers)

        def merging_fake(root, ref, *, run, say):
            spawns._answers[("git", "log", "-1")] = (0, "Merge remote-tracking branch 'origin/main' into lane/x\n", "")
            spawns._answers[("git", "log", "--format=- %s")] = (0, "- Merge remote-tracking branch 'origin/main'\n- feat: a thing\n", "")
            return ship.record_merge.MergeReport(True, ["ESPALIER_MEMORY.md"], [])

        monkeypatch.setattr(ship.record_merge, "merge_ref_in", merging_fake)
        assert ship.open_pr() == 0
        created = spawns.matching(("gh", "pr", "create"))[0]
        assert created[created.index("--title") + 1].startswith("feat: a thing")
        assert spawns.body_texts == ["- feat: a thing\n"]

    def test_a_path_with_a_merge_attribute_changed_on_both_sides_merges_first_though_the_probe_reads_clean(
            self, ship, tmp_path, forget_guard, monkeypatch):
        _write_guard(tmp_path)
        answers = _open_answers(tmp_path, diff="CHANGELOG.md\n")
        answers[("git", "diff", "--name-only", "HEAD...origin/main")] = (0, "CHANGELOG.md\n", "")
        answers[("git", "check-attr", "merge", "--")] = (0, "CHANGELOG.md: merge: union\n", "")
        answers[("git", "status", "--porcelain", "-uno")] = (0, "", "")
        spawns = _arm(ship, answers)
        calls = _stub_resolver(ship, monkeypatch, spawns)
        assert ship.open_pr() == 0
        assert len(calls) == 1 and calls[0]["ref"] == "origin/main"

    def test_a_merge_in_progress_is_refused_naming_abort_not_commit(self, ship, tmp_path, capsys):
        answers = _preflight_answers(tmp_path, dirty="UU ESPALIER_MEMORY.md\n")
        answers[("git", "rev-parse", "-q", "--verify", "MERGE_HEAD")] = (0, "abc\n", "")
        _arm(ship, answers)
        with pytest.raises(ship.Refused) as stop:
            ship.preflight()
        assert "git merge --abort" in str(stop.value) and "/commit first" not in str(stop.value)

    def test_the_handoff_push_onto_an_open_pull_request_merges_first_too(self, ship, tmp_path, monkeypatch):
        _toml(tmp_path, "handoff_push = true\n")
        answers = TestHandoffVerb._existing_pr_answers(tmp_path)
        answers[("git", "merge-tree")] = _CONFLICT_ON_MEMORY
        spawns = _arm(ship, answers)
        calls = _stub_resolver(ship, monkeypatch, spawns)
        monkeypatch.setattr(ship, "rebind", lambda dry_run=False: 0)
        assert ship.handoff() == 0
        assert len(calls) == 1 and calls[0]["ref"] == "origin/main"
        assert calls[0]["spawns_before"] <= spawns.index(("git", "push"))
        assert spawns.count(("git", "push")) == 1

    def test_preflight_prints_the_merge_verdict(self, ship, tmp_path, capsys):
        _arm(ship, _preflight_answers(tmp_path))
        assert ship.preflight() == 0
        assert "merges clean with origin/main" in capsys.readouterr().out

        answers = _preflight_answers(tmp_path)
        answers[("git", "merge-tree")] = _CONFLICT_ON_MEMORY
        _arm(ship, answers)
        assert ship.preflight() == 0
        assert ("conflicts with origin/main: `open` merges the base in first, ESPALIER_MEMORY.md resolved by shape"
                in capsys.readouterr().out)

        answers = _preflight_answers(tmp_path)
        answers[("git", "merge-tree")] = (1, "abc\nREADME.md\nESPALIER_MEMORY.md\n\nCONFLICT\n", "")
        _arm(ship, answers)
        assert ship.preflight() == 0
        out = capsys.readouterr().out
        assert "note: conflicts with origin/main on README.md" in out and "reads DIRTY" in out
        assert "the record files (ESPALIER_MEMORY.md) resolve by shape" in out

        answers = _preflight_answers(tmp_path)
        answers[("git", "diff", "--name-only")] = (0, "CHANGELOG.md\n", "")
        answers[("git", "check-attr", "merge", "--")] = (0, "CHANGELOG.md: merge: union\n", "")
        _arm(ship, answers)
        assert ship.preflight() == 0
        out = capsys.readouterr().out
        assert "CHANGELOG.md merged by this repository's attribute (GitHub's merge cannot)" in out


class TestCatchUpConflict:
    """A lane GitHub reads CONFLICTING cannot be caught up on the server; the
    verb merges the base in here, record files resolved by shape, pushes and
    re-binds. A clean BEHIND still takes the server path."""

    _BOUND_OLD = f"feat: a thing {MARKER}@0000000"

    def _answers(self, root, *, heads=None, status=""):
        answers = _catch_up_answers(root)
        conflicting = _pr(head=OLD_HEAD, title=self._BOUND_OLD, merge_state="DIRTY", mergeable="CONFLICTING")
        settled = _pr(head=HEAD, title=self._BOUND_OLD, merge_state="BLOCKED")
        answers[_list_key("lane/x")] = heads if heads is not None else [_rows(conflicting), _rows(settled)]
        answers[("git", "status", "--porcelain", "-uno")] = (0, status, "")
        answers[("git", "fetch", "origin", "main")] = (0, "", "")
        answers[("git", "fetch", "origin", "release")] = (0, "", "")
        answers[("git", "push")] = (0, "", "")
        return answers

    def test_the_pull_requests_own_base_is_merged_not_the_default_branch(self, ship, tmp_path, monkeypatch):
        """Failure-mode review: a lane based on `release` must merge
        origin/release in, not origin/main."""
        _bind_clock(ship, monkeypatch)
        conflicting = _pr(head=OLD_HEAD, title=self._BOUND_OLD, merge_state="DIRTY", mergeable="CONFLICTING",
                          base="release")
        settled = _pr(head=HEAD, title=self._BOUND_OLD, merge_state="BLOCKED", base="release")
        spawns = _arm(ship, self._answers(tmp_path, heads=[_rows(conflicting), _rows(settled)]))
        calls = _stub_resolver(ship, monkeypatch, spawns)
        assert ship.catch_up() == 0
        assert calls[0]["ref"] == "origin/release"
        assert spawns.count(("git", "fetch", "origin", "release")) == 1

    def test_a_settled_behind_state_takes_the_server_path_while_mergeable_is_still_unknown(
            self, ship, tmp_path, monkeypatch):
        """A BEHIND lane went straight to `gh pr update-branch` before the
        mergeable read existed; a still-computing `mergeable` beside a settled
        state must not turn that into a wait and a refusal (failure-mode review)."""
        _bind_clock(ship, monkeypatch)
        behind = _pr(head=OLD_HEAD, title=self._BOUND_OLD, merge_state="BEHIND", mergeable="UNKNOWN")
        moved = _pr(head=HEAD, title=self._BOUND_OLD, merge_state="BLOCKED")
        spawns = _arm(ship, self._answers(tmp_path, heads=[_rows(behind), _rows(moved)]))
        calls = _stub_resolver(ship, monkeypatch, spawns)
        assert ship.catch_up() == 0
        assert calls == [] and spawns.count(("gh", "pr", "update-branch")) == 1

    def test_a_conflicting_pull_request_is_merged_locally_pushed_and_re_bound(
            self, ship, tmp_path, monkeypatch):
        _bind_clock(ship, monkeypatch)
        spawns = _arm(ship, self._answers(tmp_path))
        calls = _stub_resolver(ship, monkeypatch, spawns)
        assert ship.catch_up() == 0
        assert len(calls) == 1 and calls[0]["ref"] == "origin/main" and calls[0]["run"] is spawns
        assert spawns.count(("gh", "pr", "update-branch")) == 0, "the server cannot make this merge"
        assert spawns.count(("git", "pull")) == 0
        pushed, edited = spawns.index(("git", "push")), spawns.index(("gh", "pr", "edit"))
        assert calls[0]["spawns_before"] <= pushed < edited
        assert spawns.count(("gh", "pr", "edit")) == 1

    def test_a_conflict_the_resolver_refuses_is_a_refusal_that_names_it(self, ship, tmp_path, monkeypatch):
        _bind_clock(ship, monkeypatch)
        spawns = _arm(ship, self._answers(tmp_path))
        _stub_resolver(ship, monkeypatch, spawns, refuses="conflicts outside the record files: README.md")
        with pytest.raises(ship.Refused) as stop:
            ship.catch_up()
        assert "beyond what the record merge resolves" in str(stop.value) and "README.md" in str(stop.value)
        assert spawns.count(("git", "push")) == 0 and spawns.count(("gh", "pr", "update-branch")) == 0

    def test_a_dirty_tree_is_refused_before_the_merge(self, ship, tmp_path, monkeypatch):
        _bind_clock(ship, monkeypatch)
        spawns = _arm(ship, self._answers(tmp_path, status=" M a.py\n"))
        calls = _stub_resolver(ship, monkeypatch, spawns)
        with pytest.raises(ship.Refused) as stop:
            ship.catch_up()
        assert "dirty" in str(stop.value) and calls == [] and spawns.mutations == []

    def test_unknown_mergeability_is_waited_out_then_acted_on(self, ship, tmp_path, monkeypatch):
        """GitHub recomputes mergeability after the base moves and answers
        UNKNOWN meanwhile (read on #88 on 2026-10-05, the moment #91 merged)."""
        _bind_clock(ship, monkeypatch)
        unknown = _pr(head=OLD_HEAD, title=self._BOUND_OLD, merge_state="UNKNOWN", mergeable="UNKNOWN")
        conflicting = _pr(head=OLD_HEAD, title=self._BOUND_OLD, merge_state="DIRTY", mergeable="CONFLICTING")
        settled = _pr(head=HEAD, title=self._BOUND_OLD, merge_state="BLOCKED")
        spawns = _arm(ship, self._answers(tmp_path, heads=[_rows(unknown), _rows(conflicting), _rows(settled)]))
        calls = _stub_resolver(ship, monkeypatch, spawns)
        assert ship.catch_up() == 0
        assert len(calls) == 1
        reads_before_merge = sum(1 for c in spawns.calls[:calls[0]["spawns_before"]]
                                 if tuple(c[:len(_list_key("lane/x"))]) == _list_key("lane/x"))
        assert reads_before_merge == 2, "one read found UNKNOWN, the poll found CONFLICTING"

    def test_unknown_mergeability_that_never_settles_is_a_refusal_to_come_back(self, ship, tmp_path, monkeypatch):
        _bind_clock(ship, monkeypatch)
        unknown = _pr(head=OLD_HEAD, title=self._BOUND_OLD, merge_state="UNKNOWN", mergeable="UNKNOWN")
        spawns = _arm(ship, self._answers(tmp_path, heads=[_rows(unknown)]))
        calls = _stub_resolver(ship, monkeypatch, spawns)
        with pytest.raises(ship.Refused) as stop:
            ship.catch_up()
        assert "has not finished computing" in str(stop.value)
        assert calls == [] and spawns.mutations == []

    def test_a_resolver_that_finds_nothing_to_merge_is_a_refusal_to_read_status(self, ship, tmp_path, monkeypatch):
        _bind_clock(ship, monkeypatch)
        spawns = _arm(ship, self._answers(tmp_path))
        _stub_resolver(ship, monkeypatch, spawns, merged=False)
        with pytest.raises(ship.Refused) as stop:
            ship.catch_up()
        assert "already reaches origin/main" in str(stop.value)
        assert spawns.count(("git", "push")) == 0

    def test_a_clean_behind_lane_still_takes_the_server_path(self, ship, tmp_path, monkeypatch):
        _bind_clock(ship, monkeypatch)
        behind = _pr(head=OLD_HEAD, title=self._BOUND_OLD, merge_state="BEHIND", mergeable="MERGEABLE")
        moved = _pr(head=HEAD, title=self._BOUND_OLD, merge_state="BLOCKED", mergeable="MERGEABLE")
        spawns = _arm(ship, self._answers(tmp_path, heads=[_rows(behind), _rows(moved)]))
        calls = _stub_resolver(ship, monkeypatch, spawns)
        assert ship.catch_up() == 0
        assert calls == []
        assert spawns.count(("gh", "pr", "update-branch")) == 1 and spawns.count(("git", "pull")) == 1

    def test_the_local_merge_re_arms_the_own_clear_marker_at_the_new_head(
            self, ship, tmp_path, monkeypatch, capsys):
        """The record merge moves HEAD as surely as the server path's pull
        does, and the marker armed for this session at the head the verb
        started from follows it once the push landed and the re-bind ran (the
        server path, the commit-after-the-handoff twin and the refusal after
        the move are driven on real git in tests/test_own_clear.py); a marker
        another session armed is left. HEAD reads OLD_HEAD once, at the verb's
        start, then HEAD: the merge moved it."""
        _bind_clock(ship, monkeypatch)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-here")
        ship.arm_own_clear(tmp_path, session_id="s-here", head=OLD_HEAD, seat="box", role="worker", brief="b")
        answers = self._answers(tmp_path)
        answers[("git", "rev-parse", "HEAD")] = [(0, f"{OLD_HEAD}\n", ""), (0, f"{HEAD}\n", "")]
        spawns = _arm(ship, answers)
        _stub_resolver(ship, monkeypatch, spawns)
        assert ship.catch_up() == 0
        marker = json.loads((tmp_path / ".espalier-state" / "own_clear.json").read_text(encoding="utf-8"))
        assert marker["head"] == HEAD, "the merge moved HEAD and left the marker armed at the old head"
        assert marker["rearmed_from"] == OLD_HEAD and marker["rearmed_by"] == "catch-up"
        assert marker["state"] == "armed" and marker["brief"] == "b"
        assert spawns.count(("git", "push")) == 1
        assert spawns.index(("gh", "pr", "edit")) < len(spawns.calls), "the re-bind ran before the re-arm"
        assert f"own-clear re-armed at {SHORT}" in capsys.readouterr().out

        ship.arm_own_clear(tmp_path, session_id="s-elsewhere", head=OLD_HEAD, seat="box", role="worker", brief="b")
        answers = self._answers(tmp_path)
        answers[("git", "rev-parse", "HEAD")] = [(0, f"{OLD_HEAD}\n", ""), (0, f"{HEAD}\n", "")]
        spawns = _arm(ship, answers)
        _stub_resolver(ship, monkeypatch, spawns)
        assert ship.catch_up() == 0
        marker = json.loads((tmp_path / ".espalier-state" / "own_clear.json").read_text(encoding="utf-8"))
        assert marker["head"] == OLD_HEAD and "rearmed_by" not in marker
        assert "armed for session s-elsewh" in capsys.readouterr().out


# ── status ───────────────────────────────────────────────────────────────────

#: The up-to-date rule's read, keyed whole: the annotation reads are `gh api` too.
_PROTECTION_KEY = ("gh", "api", "repos/{owner}/{repo}/branches/main/protection/required_status_checks")


def _status_answers(root, *, branch="lane/x", open_rows=None, merged_rows="[]",
                    checks=None, strict: bool = True) -> dict:
    """``strict`` answers the up-to-date rule ON by default: GitHub then holds
    a stale lane itself and the stale-base read stops there (TestStaleBase
    drives the rule off)."""
    answers = _reads(root, branch=branch)
    answers.update({
        _list_key(branch, "open"): open_rows if open_rows is not None else _rows(_pr()),
        _list_key(branch, "merged"): (0, merged_rows, ""),
        ("gh", "pr", "checks"): checks or (0, json.dumps(
            [{"name": "lint", "bucket": "pass"}]), ""),
        _PROTECTION_KEY: (0, json.dumps({"strict": strict, "contexts": ["lint"]}), ""),
    })
    return answers


class TestStatus:
    def test_the_required_reds_are_read_from_a_checks_answer_that_exits_nonzero(
            self, ship, tmp_path, capsys):
        checks = (1, json.dumps([
            {"name": "test (3.12)", "bucket": "fail"},
            {"name": "lint", "bucket": "pass"},
            {"name": "guard", "bucket": "fail"},
        ]), "some checks were not successful")
        _arm(ship, _status_answers(tmp_path, checks=checks))
        assert ship.status() == 0
        out = capsys.readouterr().out
        assert "required red: guard, test (3.12) -- fix, push, rebind" in out

    def test_a_green_required_set_says_no_required_check_is_red(
            self, ship, tmp_path, capsys):
        _arm(ship, _status_answers(tmp_path))
        assert ship.status() == 0
        assert "no required check is red" in capsys.readouterr().out

    def test_a_required_set_that_cannot_be_read_says_so(self, ship, tmp_path, capsys):
        _arm(ship, _status_answers(tmp_path, checks=(1, "{}", "")))
        assert ship.status() == 0
        assert "could not read which checks are required" in capsys.readouterr().out

    def test_a_branch_with_no_pull_request_says_so(self, ship, tmp_path, capsys):
        spawns = _arm(ship, _status_answers(tmp_path, open_rows=(0, "[]", "")))
        assert ship.status() == 0
        assert "no pull request for lane/x" in capsys.readouterr().out
        assert spawns.mutations == []

    def test_a_merged_pull_request_names_its_merge_commit(self, ship, tmp_path, capsys):
        merged = json.dumps([_pr(state="MERGED", merge_oid=HEAD, armed=False)])
        spawns = _arm(ship, _status_answers(
            tmp_path, open_rows=(0, "[]", ""), merged_rows=merged))
        assert ship.status() == 0
        out = capsys.readouterr().out
        assert f"merged as {SHORT}" in out
        assert "auto-merge not armed" in out
        assert spawns.count(("gh", "pr", "checks")) == 0


# ── rerun: a required cell a lost runner ended ───────────────────────────────

RUN_ID = "37375224554"
OTHER_RUN = "37368222439"
#: The two shapes measured 2026-10-05 over sixty pull-request runs of the test
#: workflow, as GitHub annotated them, and the notes that make a cancel a decision.
LOST_MID_STEP = "The operation was canceled."
NOT_ACQUIRED = "The job was not acquired by Runner of type hosted even after multiple attempts"
SUPERSEDED = "Canceling since a higher priority waiting request for CI-refs/pull/7/merge-pull_request exists"
JOB_TIMEOUT = "The job running on runner GitHub Actions 7 has exceeded the maximum execution time of 30 minutes."


def _check(name: str, bucket: str, job_id: int, run_id: str = RUN_ID) -> dict:
    return {"name": name, "bucket": bucket,
            "link": f"https://github.com/o/r/actions/runs/{run_id}/job/{job_id}"}


def _job(job_id: int, name: str, conclusion: str, steps: tuple[str, ...] = ("success",)) -> dict:
    return {"databaseId": job_id, "name": name, "status": "completed", "conclusion": conclusion,
            "steps": [{"name": f"step {i}", "number": i, "status": "completed", "conclusion": c}
                      for i, c in enumerate(steps, 1)]}


def _run_view(*jobs: dict, attempt: int = 1, status: str = "completed") -> tuple[int, str, str]:
    return (0, json.dumps({"attempt": attempt, "status": status, "conclusion": "failure",
                           "jobs": list(jobs)}), "")


def _notes(*messages: str) -> tuple[int, str, str]:
    return (0, json.dumps([{"annotation_level": "failure", "message": m} for m in messages]), "")


def _notes_key(job_id: int) -> tuple[str, ...]:
    return ("gh", "api", f"repos/{{owner}}/{{repo}}/check-runs/{job_id}/annotations")


def _rerun_answers(root, checks: list[dict], runs: dict[str, tuple] | None = None,
                   notes: dict[int, tuple] | None = None, rerun=(0, "", ""), base=None,
                   pr: dict | None = None) -> dict:
    """What `rerun` and `status` read: the required checks (gh exits 1 on a
    red), one `gh run view` per run a red cell links to, and the annotations
    of a job only when its steps leave the question open. A read the table
    does not plan is an unplanned spawn, so a row that leaves a job's notes
    out also pins that they were never fetched."""
    answers = base if base is not None else _reads(root)
    answers.update({
        _list_key("lane/x", "open"): _rows(pr or _pr()),
        ("gh", "pr", "checks"): (1, json.dumps(checks), "some checks were not successful"),
        ("gh", "run", "rerun"): rerun,
    })
    for run_id, view in (runs or {}).items():
        answers[("gh", "run", "view", run_id)] = view
    for job_id, answer in (notes or {}).items():
        answers[_notes_key(job_id)] = answer
    return answers


def _lost_mid_step(job_id: int = 11, name: str = "test (3.11)") -> dict:
    return _job(job_id, name, "failure", ("success", "cancelled", "skipped"))


def _one_lost_cell(tmp_path, *, view=None, notes=None, **kw) -> dict:
    """The #99 shape: one required cell whose runner went away mid-step."""
    return _rerun_answers(
        tmp_path, [_check("test (3.11)", "fail", 11), _check("test (3.12)", "pass", 12)],
        {RUN_ID: view or _run_view(_lost_mid_step(), _job(12, "test (3.12)", "success"))},
        notes or {11: _notes(LOST_MID_STEP)}, **kw)


class TestRerun:
    """`rerun` re-runs, once, a required cell its runner ended before its tests
    could say anything -- and nothing else. Each refusal is pinned as a
    non-event: `gh run rerun` is never spawned."""

    def test_a_cell_whose_runner_went_away_mid_step_is_re_run_once(self, ship, tmp_path, capsys):
        spawns = _arm(ship, _one_lost_cell(tmp_path))
        assert ship.rerun() == 0
        assert spawns.matching(("gh", "run", "rerun")) == [["gh", "run", "rerun", RUN_ID, "--failed"]]
        out = capsys.readouterr().out
        assert f"re-ran run {RUN_ID} once: test (3.11) (a step was cancelled, none failed)" in out

    def test_a_job_no_runner_picked_up_is_re_run_once(self, ship, tmp_path, capsys):
        spawns = _arm(ship, _rerun_answers(
            tmp_path,
            [_check("test-serial (3.13)", "cancel", 21)],
            {RUN_ID: _run_view(_job(21, "test-serial (3.13)", "cancelled", ()))},
            {21: _notes(NOT_ACQUIRED)}))
        assert ship.rerun() == 0
        assert spawns.count(("gh", "run", "rerun")) == 1
        assert "test-serial (3.13) (no runner picked it up)" in capsys.readouterr().out

    def test_the_lost_cells_of_one_run_ride_one_re_run(self, ship, tmp_path):
        spawns = _arm(ship, _rerun_answers(
            tmp_path,
            [_check("test (3.11)", "fail", 11), _check("test (3.13)", "fail", 13)],
            {RUN_ID: _run_view(_lost_mid_step(11), _lost_mid_step(13, "test (3.13)"))},
            {11: _notes(LOST_MID_STEP), 13: _notes(LOST_MID_STEP)}))
        assert ship.rerun() == 0
        assert spawns.matching(("gh", "run", "rerun")) == [["gh", "run", "rerun", RUN_ID, "--failed"]]

    def test_a_skipped_job_beside_the_lost_cell_holds_nothing(self, ship, tmp_path):
        spawns = _arm(ship, _one_lost_cell(tmp_path, view=_run_view(
            _lost_mid_step(), _job(14, "self-host", "skipped", ()))))
        assert ship.rerun() == 0
        assert spawns.count(("gh", "run", "rerun")) == 1

    def test_a_lost_job_that_is_not_required_rides_the_re_run_by_name(self, ship, tmp_path, capsys):
        spawns = _arm(ship, _one_lost_cell(
            tmp_path, view=_run_view(_lost_mid_step(), _job(14, "workflow-lint", "cancelled", ())),
            notes={11: _notes(LOST_MID_STEP), 14: _notes(NOT_ACQUIRED)}))
        assert ship.rerun() == 0
        assert spawns.count(("gh", "run", "rerun")) == 1
        assert "workflow-lint (no runner picked it up; not required)" in capsys.readouterr().out

    def test_dry_run_names_the_re_run_and_spawns_none(self, ship, tmp_path, capsys):
        spawns = _arm(ship, _one_lost_cell(tmp_path))
        assert ship.main(["rerun", "--dry-run"]) == 0
        assert f"dry-run: gh run rerun {RUN_ID} --failed (test (3.11)" in capsys.readouterr().out
        assert spawns.mutations == []

    def test_a_failed_step_is_decided_and_its_notes_are_never_read(self, ship, tmp_path):
        spawns = _arm(ship, _rerun_answers(
            tmp_path,
            [_check("test (3.11)", "fail", 11)],
            {RUN_ID: _run_view(_job(11, "test (3.11)", "failure", ("success", "failure")))}))
        with pytest.raises(ship.Refused, match=r"a required red its tests decided: test \(3\.11\)"):
            ship.rerun()
        assert spawns.mutations == []

    def test_a_failed_step_then_a_cancelled_cleanup_step_is_decided(self, ship, tmp_path):
        # The `"failure" not in steps` guard: an `if: always()` step cancelled
        # after a real failure, with the generic cancel note, is a verdict.
        spawns = _arm(ship, _one_lost_cell(tmp_path, view=_run_view(
            _job(11, "test (3.11)", "failure", ("success", "failure", "cancelled")))))
        with pytest.raises(ship.Refused, match=r"a required red its tests decided: test \(3\.11\)"):
            ship.rerun()
        assert spawns.mutations == []

    @pytest.mark.parametrize("conclusion, steps, message", [
        ("cancelled", ("success", "cancelled"), SUPERSEDED),
        ("cancelled", ("success", "cancelled"), "The run was canceled by @someone."),
        ("failure", ("success", "cancelled"), JOB_TIMEOUT),
    ], ids=["superseded-by-a-newer-run", "cancelled-by-hand", "job-outran-its-timeout"])
    def test_a_cancel_with_a_decided_note_is_never_re_run(self, ship, tmp_path, conclusion, steps, message):
        # Each carries the lost-runner note as well: the decided note wins.
        bucket = "cancel" if conclusion == "cancelled" else "fail"
        spawns = _arm(ship, _rerun_answers(
            tmp_path,
            [_check("test (3.11)", bucket, 11)],
            {RUN_ID: _run_view(_job(11, "test (3.11)", conclusion, steps))},
            {11: _notes(message, LOST_MID_STEP, NOT_ACQUIRED)}))
        with pytest.raises(ship.Refused, match=r"a required red its tests decided: test \(3\.11\)"):
            ship.rerun()
        assert spawns.mutations == []

    @pytest.mark.parametrize("notes, why", [
        (_notes("The hosted runner lost communication with the server."), "with notes this driver does not recognise"),
        ((1, "", "HTTP 404: Not Found"), "its notes could not be read"),
    ], ids=["notes-outside-the-list", "notes-unreadable"])
    def test_the_right_outline_with_notes_it_cannot_place_is_reported_unread(self, ship, tmp_path, notes, why):
        # Where a GitHub rewording lands: neither re-run nor called a test red.
        spawns = _arm(ship, _one_lost_cell(tmp_path, notes={11: notes}))
        with pytest.raises(ship.Refused, match="a required red whose cause was not read") as exc:
            ship.rerun()
        assert why in str(exc.value)
        assert f"gh run view {RUN_ID} --job 11 --log" in str(exc.value)
        assert spawns.mutations == []

    def test_a_run_that_cannot_be_read_is_unread_not_decided(self, ship, tmp_path):
        spawns = _arm(ship, _one_lost_cell(tmp_path, view=(1, "", "HTTP 502")))
        with pytest.raises(ship.Refused, match=f"run {RUN_ID} could not be read"):
            ship.rerun()
        assert spawns.mutations == []

    def test_a_check_that_is_not_an_actions_job_is_decided(self, ship, tmp_path):
        spawns = _arm(ship, _rerun_answers(
            tmp_path, [{"name": "verify", "bucket": "fail", "link": "https://example.invalid/status/9"}]))
        with pytest.raises(ship.Refused, match="a required red its tests decided: verify"):
            ship.rerun()
        assert spawns.count(("gh", "run", "view")) == 0
        assert spawns.mutations == []

    def test_a_run_already_re_run_is_not_re_run_again(self, ship, tmp_path):
        spawns = _arm(ship, _one_lost_cell(tmp_path, view=_run_view(_lost_mid_step(), attempt=2)))
        with pytest.raises(ship.Refused, match=r"already re-run \(attempt 2\)"):
            ship.rerun()
        assert spawns.mutations == []

    def test_a_run_still_going_is_not_re_run_yet(self, ship, tmp_path):
        spawns = _arm(ship, _one_lost_cell(tmp_path, view=_run_view(_lost_mid_step(), status="in_progress")))
        with pytest.raises(ship.Refused, match="still running"):
            ship.rerun()
        assert spawns.mutations == []

    def test_a_decided_red_elsewhere_in_the_run_holds_the_re_run_and_names_the_way_round(self, ship, tmp_path):
        # `--failed` re-runs every failed job in the run: a lint red that is not
        # required would be retried too, and a flaky one would come back green.
        spawns = _arm(ship, _one_lost_cell(tmp_path, view=_run_view(
            _lost_mid_step(), _job(14, "lint", "failure", ("success", "failure")))))
        with pytest.raises(ship.Refused, match=r"also holds lint \(a step failed\)") as exc:
            ship.rerun()
        assert f"gh run rerun {RUN_ID} --job 11" in str(exc.value)
        assert spawns.mutations == []

    def test_a_decided_red_in_another_run_holds_every_re_run(self, ship, tmp_path):
        spawns = _arm(ship, _rerun_answers(
            tmp_path,
            [_check("test (3.11)", "fail", 11), _check("verify", "fail", 31, run_id=OTHER_RUN)],
            {RUN_ID: _run_view(_lost_mid_step()),
             OTHER_RUN: _run_view(_job(31, "verify", "failure", ("failure",)))},
            {11: _notes(LOST_MID_STEP)}))
        with pytest.raises(ship.Refused, match="a required red its tests decided: verify") as exc:
            ship.rerun()
        assert "a rebind does not" in str(exc.value)
        assert spawns.mutations == []

    def test_a_held_run_holds_the_one_that_could_go(self, ship, tmp_path):
        spawns = _arm(ship, _rerun_answers(
            tmp_path,
            [_check("test (3.11)", "fail", 11), _check("benchmark", "fail", 41, run_id=OTHER_RUN)],
            {RUN_ID: _run_view(_lost_mid_step()),
             OTHER_RUN: _run_view(_lost_mid_step(41, "benchmark"), attempt=2)},
            {11: _notes(LOST_MID_STEP), 41: _notes(LOST_MID_STEP)}))
        with pytest.raises(ship.Refused, match="waits on the held run above"):
            ship.rerun()
        assert spawns.mutations == []

    @pytest.mark.parametrize("merge_state", ["BEHIND", "DIRTY"])
    def test_a_lane_behind_or_in_conflict_goes_to_catch_up_first(self, ship, tmp_path, merge_state):
        spawns = _arm(ship, _one_lost_cell(tmp_path, pr=_pr(merge_state=merge_state)))
        with pytest.raises(ship.Refused, match="catch-up re-runs every cell"):
            ship.rerun()
        assert spawns.mutations == []

    def test_no_lost_cell_re_runs_nothing_and_says_so(self, ship, tmp_path, capsys):
        spawns = _arm(ship, _rerun_answers(
            tmp_path, [_check("test (3.11)", "pass", 11), _check("verify", "pending", 31)]))
        assert ship.main(["rerun"]) == 0
        assert "no required cell was ended by a lost runner; 1 still running" in capsys.readouterr().out
        assert spawns.mutations == []

    def test_a_refused_re_run_is_a_named_stop(self, ship, tmp_path):
        _arm(ship, _one_lost_cell(tmp_path, rerun=(1, "", "HTTP 403: Resource not accessible by integration")))
        with pytest.raises(ship.Refused, match="gh run rerun .* failed: HTTP 403"):
            ship.rerun()


class TestStatusNamesTheCellsALostRunnerEnded:
    """`status` is read-only, so it names what `rerun` would do and never does
    it; and a cancelled required cell is never reported as not red."""

    def test_a_cancelled_required_cell_is_never_reported_as_not_red(self, ship, tmp_path, capsys):
        _arm(ship, _rerun_answers(
            tmp_path,
            [_check("test (3.11)", "cancel", 11)],
            {RUN_ID: _run_view(_job(11, "test (3.11)", "cancelled", ("success", "cancelled")))},
            {11: _notes(SUPERSEDED)},
            base=_status_answers(tmp_path)))
        assert ship.status() == 0
        out = capsys.readouterr().out
        assert "required red: test (3.11) -- fix, push, rebind" in out
        assert "no required check is red" not in out

    def test_a_lost_cell_is_named_apart_with_the_verb_that_re_runs_it(self, ship, tmp_path, capsys):
        spawns = _arm(ship, _one_lost_cell(tmp_path, base=_status_answers(tmp_path)))
        assert ship.status() == 0
        out = capsys.readouterr().out
        assert ("required, runner lost: test (3.11) (a step was cancelled, none failed) -- "
                f"`ship.py rerun` re-runs run {RUN_ID} once") in out
        assert "required red" not in out
        assert spawns.mutations == []

    def test_a_lost_cell_already_re_run_is_named_as_yours(self, ship, tmp_path, capsys):
        _arm(ship, _one_lost_cell(tmp_path, view=_run_view(_lost_mid_step(), attempt=2),
                                  base=_status_answers(tmp_path)))
        assert ship.status() == 0
        out = capsys.readouterr().out
        assert "required, runner lost: test (3.11) (a step was cancelled, none failed): " in out
        assert "already re-run (attempt 2)" in out
        assert "`ship.py rerun`" not in out

    def test_a_lost_cell_behind_a_decided_red_is_held_not_offered(self, ship, tmp_path, capsys):
        _arm(ship, _rerun_answers(
            tmp_path,
            [_check("test (3.11)", "fail", 11), _check("verify", "fail", 31, run_id=OTHER_RUN)],
            {RUN_ID: _run_view(_lost_mid_step()),
             OTHER_RUN: _run_view(_job(31, "verify", "failure", ("failure",)))},
            {11: _notes(LOST_MID_STEP)},
            base=_status_answers(tmp_path)))
        assert ship.status() == 0
        out = capsys.readouterr().out
        assert "required red: verify -- fix, push, rebind" in out
        assert "waits on the required red above" in out
        assert "`ship.py rerun`" not in out

    def test_a_cell_it_cannot_place_is_a_red_whose_cause_was_not_read(self, ship, tmp_path, capsys):
        _arm(ship, _one_lost_cell(tmp_path, notes={11: _notes("The hosted runner lost communication.")},
                                  base=_status_answers(tmp_path)))
        assert ship.status() == 0
        out = capsys.readouterr().out
        assert "required red, cause not read: test (3.11)" in out
        assert "fix, push, rebind" not in out


# ── release ──────────────────────────────────────────────────────────────────

def _release_answers(root, *, branch="lane/x", merged=None, local_tag=(1, "", ""),
                     remote=None, tag=(0, "", ""), push=(0, "", ""),
                     create=(0, "https://example.invalid/releases/v1.2.3\n", "")) -> dict:
    answers = _reads(root, branch=branch)
    answers.update({
        _list_key(branch, "merged"): merged if merged is not None else _rows(
            _pr(state="MERGED", merge_oid=HEAD, armed=False)),
        ("git", "rev-parse", "-q"): local_tag,
        ("git", "fetch"): (0, "", ""),   # the merge commit, fetched before the tag
        ("git", "ls-remote"): remote or [(0, "", ""), (0, f"{HEAD}\trefs/tags/v1.2.3\n", "")],
        ("git", "tag"): tag,
        ("git", "push"): push,
        ("gh", "release", "create"): create,
    })
    return answers


def _pyproject(root: Path, version: str = "1.2.3") -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "espalier"\nversion = "{version}"\n', encoding="utf-8")


class TestRelease:
    def test_the_merge_commit_is_tagged_then_pushed_then_the_release_is_created(
            self, ship, tmp_path, capsys):
        _pyproject(tmp_path)
        spawns = _arm(ship, _release_answers(tmp_path))
        assert ship.release("v1.2.3") == 0
        tagged = spawns.index(("git", "tag"))
        pushed = spawns.index(("git", "push"))
        released = spawns.index(("gh", "release", "create"))
        assert 0 <= tagged < pushed < released
        assert spawns.matching(("git", "tag"))[0][-1] == HEAD
        assert f"v1.2.3 on {SHORT}, pushed" in capsys.readouterr().out

    def test_a_tag_that_is_not_the_trees_version_is_refused_before_any_tag_or_push(
            self, ship, tmp_path):
        _pyproject(tmp_path, "1.2.3")
        spawns = _arm(ship, _release_answers(tmp_path))
        with pytest.raises(ship.Refused) as stop:
            ship.release("v9.9.9")
        assert "is not the tree's version v1.2.3" in str(stop.value)
        assert spawns.mutations == []

    def test_a_name_that_is_not_a_release_tag_is_refused(self, ship, tmp_path):
        _pyproject(tmp_path)
        spawns = _arm(ship, _release_answers(tmp_path))
        with pytest.raises(ship.Refused) as stop:
            ship.release("1.2.3")
        assert "is not a release tag" in str(stop.value)
        assert spawns.mutations == []

    def test_a_tree_whose_version_cannot_be_read_is_refused(self, ship, tmp_path):
        spawns = _arm(ship, _release_answers(tmp_path))
        with pytest.raises(ship.Refused) as stop:
            ship.release("v1.2.3")
        assert "could not read the tree's version" in str(stop.value)
        assert spawns.mutations == []

    def test_an_unmerged_pull_request_is_refused_before_any_tag_or_push(
            self, ship, tmp_path):
        _pyproject(tmp_path)
        spawns = _arm(ship, _release_answers(tmp_path, merged=(0, "[]", "")))
        with pytest.raises(ship.Refused) as stop:
            ship.release("v1.2.3")
        assert "no merged pull request for lane/x" in str(stop.value)
        assert "never the lane" in str(stop.value)
        assert spawns.mutations == []

    def test_a_tag_that_already_exists_locally_is_refused_before_any_tag_or_push(
            self, ship, tmp_path):
        _pyproject(tmp_path)
        spawns = _arm(ship, _release_answers(tmp_path, local_tag=(0, f"{HEAD}\n", "")))
        with pytest.raises(ship.Refused) as stop:
            ship.release("v1.2.3")
        assert "already exists locally" in str(stop.value)
        assert spawns.mutations == []

    def test_a_tag_already_on_origin_is_refused_before_any_tag_or_push(
            self, ship, tmp_path):
        _pyproject(tmp_path)
        spawns = _arm(ship, _release_answers(
            tmp_path, remote=[(0, f"{HEAD}\trefs/tags/v1.2.3\n", "")]))
        with pytest.raises(ship.Refused) as stop:
            ship.release("v1.2.3")
        assert "already exists on origin" in str(stop.value)
        assert spawns.mutations == []

    def test_dry_run_tags_nothing_and_pushes_nothing(self, ship, tmp_path, capsys):
        _pyproject(tmp_path)
        spawns = _arm(ship, _release_answers(tmp_path))
        assert ship.release("v1.2.3", dry_run=True) == 0
        assert spawns.mutations == []
        assert "dry-run" in capsys.readouterr().out

    def test_a_tag_that_cannot_be_created_is_refused_before_the_push(
            self, ship, tmp_path):
        _pyproject(tmp_path)
        spawns = _arm(ship, _release_answers(tmp_path, tag=(1, "", "cannot lock ref")))
        with pytest.raises(ship.Refused) as stop:
            ship.release("v1.2.3")
        assert "git tag failed" in str(stop.value)
        assert spawns.count(("git", "push")) == 0
        assert spawns.count(("gh", "release", "create")) == 0

    def test_a_rejected_tag_push_is_refused_before_the_release(self, ship, tmp_path):
        _pyproject(tmp_path)
        spawns = _arm(ship, _release_answers(tmp_path, push=(1, "", "denied")))
        with pytest.raises(ship.Refused) as stop:
            ship.release("v1.2.3")
        assert "the tag push was rejected" in str(stop.value)
        assert spawns.count(("gh", "release", "create")) == 0

    def test_a_tag_that_does_not_read_back_from_origin_is_refused_before_the_release(
            self, ship, tmp_path):
        _pyproject(tmp_path)
        spawns = _arm(ship, _release_answers(tmp_path, remote=[(0, "", "")]))
        with pytest.raises(ship.Refused) as stop:
            ship.release("v1.2.3")
        assert "does not read back from origin" in str(stop.value)
        assert spawns.count(("gh", "release", "create")) == 0

    def test_a_failed_release_creation_is_refused_with_the_tag_named_as_pushed(
            self, ship, tmp_path):
        _pyproject(tmp_path)
        _arm(ship, _release_answers(tmp_path, create=(1, "", "release already exists")))
        with pytest.raises(ship.Refused) as stop:
            ship.release("v1.2.3")
        assert "gh release create failed" in str(stop.value)
        assert "the tag is on origin" in str(stop.value)


class TestRecordFileMarkersStopTheShip:
    """A lane whose record file carries a merge-conflict marker reds every
    required cell (the guard's check is unconditional), so the driver stops it
    here: preflight names it, open and handoff refuse. The check is the guard's
    own, loaded by path from the tree; a tree with no guard, or a guard from
    before the check, leaves the question to the gate (failure-mode review,
    2026-10-05). Marker lines are built, never written."""

    @staticmethod
    def _real_guard(root: Path) -> None:
        guard = root / "tools" / "cc" / "ci_guard.py"
        guard.parent.mkdir(parents=True, exist_ok=True)
        guard.write_bytes((ROOT / "tools" / "cc" / "ci_guard.py").read_bytes())

    @staticmethod
    def _half_merge(root: Path) -> None:
        memory = root / "ESPALIER_MEMORY.md"
        memory.write_text(
            memory.read_text(encoding="utf-8")
            + "<" * 7 + " HEAD\n| 2026-10-05 | ours |\n" + "=" * 7 + "\n",
            encoding="utf-8",
        )

    def test_preflight_names_the_marker_and_the_refusal_to_come(
            self, ship, tmp_path, capsys, forget_guard):
        self._real_guard(tmp_path)
        _memory(tmp_path, "2026-10-05")
        self._half_merge(tmp_path)
        spawns = _arm(ship, _preflight_answers(tmp_path))
        assert ship.preflight() == 0
        out = capsys.readouterr().out
        assert "`open` will refuse this lane" in out
        assert "ESPALIER_MEMORY.md:4: " + "<" * 7 in out
        assert spawns.mutations == []

    def test_open_and_handoff_refuse_by_file_and_line(self, ship, tmp_path, forget_guard):
        self._real_guard(tmp_path)
        _memory(tmp_path, "2026-10-05")
        self._half_merge(tmp_path)
        with pytest.raises(ship.Refused) as stop:
            ship._refuse_a_marked_record(tmp_path)
        assert "ESPALIER_MEMORY.md:4: " + "<" * 7 in str(stop.value)
        assert "ESPALIER_MEMORY.md:6: " + "=" * 7 in str(stop.value)
        assert "indent the quote by one space" in str(stop.value)

    def test_a_clean_record_passes_and_no_guard_leaves_it_to_the_gate(
            self, ship, tmp_path, forget_guard):
        _memory(tmp_path, "2026-10-05")
        assert ship.record_file_markers(tmp_path) == []        # no guard on this tree
        self._real_guard(tmp_path)
        assert ship.record_file_markers(tmp_path) == []        # a clean record
        ship._refuse_a_marked_record(tmp_path)                 # does not raise

    def test_a_guard_from_before_the_check_leaves_it_to_the_gate(
            self, ship, tmp_path, forget_guard):
        _write_guard(tmp_path)                                 # is_protected only
        _memory(tmp_path, "2026-10-05")
        self._half_merge(tmp_path)
        assert ship.record_file_markers(tmp_path) == []


class TestAShippedLaneReleasesItsClaims:
    """A claim's lifetime is the lane's time on this machine: once `open` has
    pushed the lane (or `handoff` has pushed onto its open pull request), the
    driver closes this machine's live claims on the lane through the mail
    channel. Nothing where the channel is absent or the box is unnamed; a
    failure is said with the one command that closes them, and never fails a
    push that landed (the claims-at-the-write lane, 2026-10-05)."""

    @staticmethod
    def _channel(calls: list, *, raises: Exception | None = None):
        def release_lane(root, lane, text="", **kw):
            if raises is not None:
                raise raises
            calls.append((Path(root), lane, text))
            return "abc1234"
        return types.SimpleNamespace(release_lane=release_lane)

    def test_open_releases_the_lanes_claims_after_the_push_lands(
            self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        _write_guard(tmp_path)
        calls: list = []
        monkeypatch.setattr(ship, "_MAIL", self._channel(calls))
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        assert calls == [(tmp_path, "lane/x", "Lane shipped as #7; claims closed.")]
        # the release comes after the create and the arm, never before
        assert spawns.count(("gh", "pr", "create")) == 1 and spawns.count(("gh", "pr", "merge")) == 1
        assert "#7 open, auto-merge armed, one push" in capsys.readouterr().out

    def test_a_refused_release_is_said_and_does_not_fail_the_push(
            self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        _write_guard(tmp_path)
        monkeypatch.setattr(ship, "_MAIL", self._channel([], raises=RuntimeError("origin refused the push")))
        _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        out = capsys.readouterr().out
        assert "were not released (origin refused the push)" in out
        assert "mail.py send --type release --lane lane/x" in out

    def test_a_tree_without_the_channel_ships_as_before(self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        _write_guard(tmp_path)
        monkeypatch.setattr(ship, "_mail_module", lambda: None)
        _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        assert "released" not in capsys.readouterr().out

    def test_the_real_channel_sends_nothing_from_an_unnamed_box(self, ship, tmp_path, monkeypatch):
        """tmp_path is no repository, so the channel reads no name there and
        the release is a no-op: the real module, loaded by path, says nothing."""
        monkeypatch.setattr(ship, "_MAIL", None)
        said: list[str] = []
        monkeypatch.setattr(ship, "_say", said.append)
        monkeypatch.setattr(ship, "_note", said.append)
        ship._release_claims(tmp_path, "lane/x", "x")
        assert said == []

    def test_handoff_onto_an_open_pull_request_releases_after_the_rebind(
            self, ship, tmp_path, monkeypatch):
        _toml(tmp_path, "handoff_push = true\n")
        calls: list = []
        monkeypatch.setattr(ship, "_MAIL", self._channel(calls))
        _arm(ship, TestHandoffVerb()._existing_pr_answers(tmp_path))
        monkeypatch.setattr(ship, "rebind", lambda dry_run=False: 0)
        assert ship.handoff() == 0
        assert calls == [(tmp_path, "lane/x", "Handoff pushed onto the open pull request; claims closed.")]

    def test_a_refusal_after_the_push_still_releases(self, ship, tmp_path, forget_guard, monkeypatch):
        """The lane is on origin the moment the push lands; a pull request the
        driver could not create or arm leaves the operator finishing by hand,
        with the claims already closed (failure-mode review, 2026-10-05)."""
        _write_guard(tmp_path)
        calls: list = []
        monkeypatch.setattr(ship, "_MAIL", self._channel(calls))
        _arm(ship, _open_answers(tmp_path, create=(1, "", "gh: boom")))
        with pytest.raises(ship.Refused, match="gh pr create failed"):
            ship.open_pr()
        assert calls == [(tmp_path, "lane/x", "Lane pushed; claims closed.")]


class TestTheNoticeAfterAPush:
    """TP-702 Wave 2 (2-C): once `open` or `handoff` has pushed, the driver
    prints the lane's overlaps with every live claim of another seat and every
    open pull request, in the board's words, and changes nothing else: a
    failed read is one note and the push stands. The release comes first, so
    a notice that is slow or interrupted never leaves the claims live. Driven
    on the scratch root with every spawn tabled; the board's own read is
    pinned in tests/test_board.py::TestOverlapsSection (its lane-notice rows)."""

    @staticmethod
    def _board(seen: list, lines=("overlaps: none",), raises: Exception | None = None):
        def lane_overlap_lines(root, base, lane, number, head, **kw):
            if raises is not None:
                raise raises
            seen.append(("notice", Path(root), base, lane, str(number), head))
            return list(lines)
        return types.SimpleNamespace(lane_overlap_lines=lane_overlap_lines)

    @staticmethod
    def _channel(seen: list):
        return types.SimpleNamespace(release_lane=lambda root, lane, text="", **kw: seen.append(("release", lane)))

    def test_open_prints_the_notice_after_the_push_and_the_release(
            self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        """Dies to: the notice dropped from `open`, read before the push, or read
        before the release (an interrupted notice would leave the claims live)."""
        _write_guard(tmp_path)
        seen: list = []
        line = "overlaps: win (lane/y) and #7 air-work (lane/x) meet at a.py::f"
        monkeypatch.setattr(ship, "_BOARD", self._board(seen, lines=(line,)))
        monkeypatch.setattr(ship, "_MAIL", self._channel(seen))
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        assert seen == [("release", "lane/x"), ("notice", tmp_path, "main", "lane/x", "7", HEAD)]
        assert spawns.count(("git", "push")) == 1
        out = capsys.readouterr().out
        assert out.index("#7 open, auto-merge armed") < out.index(line)

    def test_handoff_prints_the_notice_after_the_rebind(self, ship, tmp_path, monkeypatch):
        """Dies to: the notice dropped from `handoff`."""
        _toml(tmp_path, "handoff_push = true\n")
        seen: list = []
        monkeypatch.setattr(ship, "_BOARD", self._board(seen))
        monkeypatch.setattr(ship, "_MAIL", self._channel(seen))
        _arm(ship, TestHandoffVerb()._existing_pr_answers(tmp_path))
        monkeypatch.setattr(ship, "rebind", lambda dry_run=False: 0)
        assert ship.handoff() == 0
        assert [s[0] for s in seen] == ["release", "notice"] and seen[1][3] == "lane/x" and seen[1][5] == HEAD

    def test_a_failed_read_is_one_note_and_the_push_stands(
            self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        """Dies to: a notice failure raised out of a push that landed."""
        _write_guard(tmp_path)
        seen: list = []
        monkeypatch.setattr(ship, "_BOARD", self._board(seen, raises=RuntimeError("gh pr list timed out")))
        monkeypatch.setattr(ship, "_MAIL", self._channel(seen))
        _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        assert seen == [("release", "lane/x")]
        assert "note: the overlap notice was not read (gh pr list timed out); the board" in capsys.readouterr().out

    def test_a_tree_without_the_board_ships_as_before(self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        _write_guard(tmp_path)
        monkeypatch.setattr(ship, "_board_module", lambda: None)
        _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        assert "overlap" not in capsys.readouterr().out

    def test_the_real_board_loads_beside_the_driver(self, ship, monkeypatch):
        """Dies to: a board that no longer loads by path (every notice would read
        'not read' while every stand-in row stays green)."""
        monkeypatch.setattr(ship, "_BOARD", None)
        board = ship._board_module()
        assert callable(board.lane_overlap_lines) and callable(board.overlap_lines)


# ── TP-701 B-3: a push from a checkout two live sessions share is refused ────

def _two_sessions() -> list[dict]:
    return [{"pid": 4242, "entrypoint": "cli"}, {"pid": 4343, "entrypoint": "claude-vscode"}]


class TestASharedCheckoutStopsThePush:
    """Two live sessions in one checkout share its branch and index, so a push
    from either ships the other's commits too. ``open``, ``handoff`` (before
    ``lane`` can switch the branch), ``lane`` and ``catch-up`` refuse that
    state before anything moves; ``preflight`` says it. Only Claude Code's own
    registry can refuse: an unreadable one, or the session markers alone, is a
    note and the push goes ahead; ``ESPALIER_SHARED_CHECKOUT_OK=<reason>`` lets
    a push past an entry the registry got wrong, and says so."""

    def test_two_sessions_refuse_open_before_anything_moves(self, ship, tmp_path, forget_guard):
        _write_guard(tmp_path)
        ship._SYNC = _oracle(_two_sessions())
        spawns = _arm(ship, _open_answers(tmp_path))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        said = str(stop.value)
        assert said.startswith("2 live sessions work in this checkout (pid 4242 (cli); pid 4343 (claude-vscode); "
                               f"the entries are under {Path('cfg') / 'sessions'})")
        assert "Close one (a window or an editor tab)" in said and "ESPALIER_SHARED_CHECKOUT_OK=<reason>" in said
        assert "Core Rule" not in said
        assert spawns.mutations == []

    def test_the_caller_alone_ships(self, ship, tmp_path, forget_guard, capsys):
        _write_guard(tmp_path)
        ship._SYNC = _oracle(_two_sessions()[:1], caller={"pid": 4242, "entrypoint": "cli"})
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        assert spawns.count(("git", "push")) == 1
        assert "cannot be told" not in capsys.readouterr().out

    def test_a_caller_acting_here_from_its_own_checkout_counts(self, ship, tmp_path, forget_guard):
        """A clone session pushing from inside a worktree a seat's session is
        live in: one session placed here, the caller from elsewhere. Dies to:
        counting only the sessions placed here."""
        _write_guard(tmp_path)
        ship._SYNC = _oracle(_two_sessions()[:1], caller={"pid": 9999, "entrypoint": "cli"})
        spawns = _arm(ship, _open_answers(tmp_path))
        with pytest.raises(ship.Refused, match=r"2 live sessions work in this checkout \(pid 4242 \(cli\); pid 9999"):
            ship.open_pr()
        assert spawns.mutations == []

    @pytest.mark.parametrize("oracle", [
        _oracle(None, oracle="", note="Claude Code's session registry could not be read in full"),
        _oracle(_two_sessions(), oracle="markers", note="Claude Code's session registry could not be read in full"),
    ], ids=["nobody-can-tell", "markers-alone"])
    def test_an_answer_the_registry_cannot_give_is_a_note_and_the_push_goes_ahead(
            self, ship, tmp_path, forget_guard, capsys, oracle):
        """Dies to: refusing on the markers, which outlive a closed window by
        hours and would stop every seat at once."""
        _write_guard(tmp_path)
        ship._SYNC = oracle
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        assert spawns.count(("git", "push")) == 1
        out = capsys.readouterr().out
        assert "note: who else works in this checkout cannot be told (Claude Code's session registry" in out

    def test_the_override_lets_the_push_through_and_says_why(self, ship, tmp_path, forget_guard, monkeypatch,
                                                            capsys):
        _write_guard(tmp_path)
        ship._SYNC = _oracle(_two_sessions())
        monkeypatch.setenv("ESPALIER_SHARED_CHECKOUT_OK", "pid 4343 is a reused pid, checked by hand")
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0 and spawns.count(("git", "push")) == 1
        assert ("note: pushing beside 2 live sessions in this checkout (ESPALIER_SHARED_CHECKOUT_OK: pid 4343 is a "
                "reused pid, checked by hand)") in capsys.readouterr().out

    def test_handoff_onto_an_open_pull_request_refuses_before_its_push(self, ship, tmp_path):
        _toml(tmp_path, "handoff_push = true\n")
        ship._SYNC = _oracle(_two_sessions())
        spawns = _arm(ship, TestHandoffVerb._existing_pr_answers(tmp_path))
        with pytest.raises(ship.Refused, match="2 live sessions work in this checkout"):
            ship.handoff()
        assert spawns.mutations == []

    def test_handoff_on_the_default_branch_refuses_before_lane_switches_it(self, ship, tmp_path):
        """`lane` switches this checkout's branch: a second session here would
        keep committing onto the lane it was moved to. Dies to: asking only in
        `open`, after `lane` has run (the failure-mode review's M4)."""
        _toml(tmp_path, "handoff_push = true\n")
        ship._SYNC = _oracle(_two_sessions())
        answers = _lane_answers(tmp_path)
        answers[("git", "status", "--porcelain", "-uno")] = (0, "", "")
        spawns = _arm(ship, answers)
        with pytest.raises(ship.Refused, match="2 live sessions work in this checkout"):
            ship.handoff()
        assert spawns.mutations == []

    def test_the_lane_verb_refuses_before_it_moves_anything(self, ship, tmp_path):
        ship._SYNC = _oracle(_two_sessions())
        spawns = _arm(ship, _lane_answers(tmp_path))
        with pytest.raises(ship.Refused, match="2 live sessions work in this checkout"):
            ship.lane()
        assert spawns.mutations == []

    def test_catch_up_refuses_before_it_moves_the_lane(self, ship, tmp_path):
        ship._SYNC = _oracle(_two_sessions())
        spawns = _arm(ship, _catch_up_answers(tmp_path))
        with pytest.raises(ship.Refused, match="2 live sessions work in this checkout"):
            ship.catch_up()
        assert spawns.mutations == []

    def test_preflight_says_open_will_refuse(self, ship, tmp_path, capsys):
        ship._SYNC = _oracle(_two_sessions())
        _arm(ship, _preflight_answers(tmp_path))
        assert ship.preflight() == 0
        assert "note: `open` will refuse this lane: 2 live sessions work in this checkout" in capsys.readouterr().out

    def test_the_real_oracle_is_loaded_by_path_and_reads_the_registry(self, ship, tmp_path, monkeypatch):
        """No stand-in: the deployed checkout_sync.py beside the script, a
        registry of two live entries in this checkout. Dies to: an oracle
        import that fails on a fresh deploy, or a reader of another shape."""
        ship._SYNC = None
        for name in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_CODE_SESSION_ID"):
            monkeypatch.delenv(name, raising=False)
        sync = ship._sync_module()
        assert sync is not None and sync.__file__ == str(SHIP.parent / "checkout_sync.py")
        monkeypatch.setattr(sync, "ancestor_pids", lambda depth=8: [])
        cfg = tmp_path / "cfg"
        (cfg / "sessions").mkdir(parents=True)
        for pid, entry in ((os.getpid(), "cli"), (os.getppid(), "sdk-cli")):
            (cfg / "sessions" / f"{pid}.json").write_text(json.dumps(
                {"pid": pid, "sessionId": f"s{pid}", "cwd": str(tmp_path), "entrypoint": entry}), encoding="utf-8")
        monkeypatch.setattr(sync, "claude_config_dirs", lambda: [cfg])
        who, hints = ship.shared_checkout(tmp_path)
        assert sorted(who) == sorted([f"pid {os.getpid()} (cli)", f"pid {os.getppid()} (sdk-cli)"])
        assert hints == f"the entries are under {cfg / 'sessions'}"


# ── TP-479 B-3: a red base, one open pull request per seat, a stale base ──────

#: The base's post-merge proof, newest first: red on top of a green.
_RED_BASE = TestPreflight._runs(("completed", "failure"), ("completed", "success"))


class TestARedBaseRefusesOpen:
    """Nothing lands on a red base: `open` refuses to arm a lane while the
    base's newest post-merge verdict is red, lets a `revert/` lane through (the
    revert is what clears it), and names the pull requests whose armed
    auto-merge would land on the red base, each with the command that disarms
    it. Moved here from Wave A's review, where the board only said so."""

    def test_open_refuses_and_names_the_armed_pull_requests(self, ship, tmp_path, forget_guard):
        _write_guard(tmp_path)
        others = json.dumps([{"number": 41, "headRefName": "lane/y", "autoMergeRequest": {"x": 1}},
                             {"number": 42, "headRefName": "lane/z", "autoMergeRequest": None}])
        spawns = _arm(ship, _open_answers(tmp_path, open_prs=others, base_runs=_RED_BASE))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        text = str(stop.value)
        assert "main red after merge: post-merge.yml run 900" in text
        assert "Nothing lands on a red base" in text and "revert/" in text
        assert "#41 (gh pr merge --disable-auto 41)" in text and "#42" not in text
        assert spawns.mutations == []

    def test_a_revert_lane_opens_on_a_red_base(self, ship, tmp_path, forget_guard):
        """Dies to: a refusal with no way out but disabling the check."""
        _write_guard(tmp_path)
        spawns = _arm(ship, _open_answers(tmp_path, branch="revert/abc1234", base_runs=_RED_BASE))
        assert ship.open_pr() == 0
        assert spawns.count(("gh", "pr", "create")) == 1

    def test_preflight_says_open_will_refuse(self, ship, tmp_path, capsys):
        _memory(tmp_path, "2026-10-09")
        _arm(ship, _preflight_answers(tmp_path, base_runs=_RED_BASE))
        assert ship.preflight() == 0
        assert "note: `open` will refuse this lane: main red after merge" in capsys.readouterr().out

    def test_preflight_on_a_revert_lane_says_it_is_let_through(self, ship, tmp_path, capsys):
        _memory(tmp_path, "2026-10-09")
        answers = _preflight_answers(tmp_path, base_runs=_RED_BASE)
        answers[("git", "branch", "--show-current")] = (0, "revert/abc1234\n", "")
        _arm(ship, answers)
        assert ship.preflight() == 0
        out = capsys.readouterr().out
        assert "this is a revert/ lane, which `open` lets through" in out and "will refuse" not in out

    def test_a_handoff_push_onto_an_armed_pull_request_names_the_disarm(self, ship, tmp_path, monkeypatch, capsys):
        """The handoff's row still reaches the pull request (no refusal), but
        its auto-merge, armed before the base went red, would land on it."""
        _toml(tmp_path, "handoff_push = true\n")
        monkeypatch.setattr(ship, "_mail_module", lambda: None)
        _arm(ship, TestHandoffVerb._existing_pr_answers(tmp_path, base_runs=_RED_BASE))
        monkeypatch.setattr(ship, "rebind", lambda dry_run=False: 0)
        assert ship.handoff() == 0
        assert "gh pr merge --disable-auto 7 until the revert merges" in capsys.readouterr().out


#: The dispatcher's ruling on a red base: an ack id as the channel mints them.
_RULING = "20261030T120000Z-air-ab12cd"


def _ruling_ack(run: str = "900", *, machine: str = "air", ack_id: str = _RULING, text: str | None = None,
                lane: str = "lane/x", kind: str = "ack") -> dict:
    """A message as the mail channel stores it: by default the dispatcher's
    gridlock ack ruling a fix-forward on the post-merge run ``run`` for the
    fixture's lane, under the fixed head the driver reads the run from."""
    if text is None:
        text = (f"gridlock: fix forward run {run}; the red is pytest's, outside every suspect's diff, and "
                "reproduces at the last green base")
    return {"v": 1, "id": ack_id, "type": kind, "from": machine, "at": "2026-10-30T12:00:00Z",
            "re": {"lane": lane, "classes": [], "paths": [], "ids": []},
            "text": text, "ack": "20261030T110000Z-air-work-0f0f0f"}


def _ruling_channel(by_machine: dict, *, dispatcher, how: str, unusable: str, real):
    """A mail channel stood in: the local refs' messages by machine, the
    dispatcher setting, and what the verbs after a push ask of it. The ruling's
    reader is ``real``'s (the channel module itself: the one home the board's
    red line reads too), so the stand-in carries the channel and never the rule."""
    return types.SimpleNamespace(
        read_mail=lambda root, **kw: (dict(by_machine), {}),
        dispatcher_setting=lambda root: (dispatcher, how),
        DISPATCHER_UNUSABLE=unusable,
        MACHINE_UNREAD="git config could not be read",
        machine_setting=lambda root, **kw: ("air-work", "stubbed"),
        lane_seats=lambda by_machine: {},
        release_lane=lambda root, lane, text="", **kw: None,
        pending=lambda *a, **kw: [],
        Unresolvable=Exception,
        fetch_records=lambda root, **kw: (True, ""),
        fix_forward_ruling=real.fix_forward_ruling,
        fix_forward_rulings=real.fix_forward_rulings,
        MESSAGE_ID_RE=real.MESSAGE_ID_RE)


def _real_mail():
    """The channel module loaded by path, apart from the driver's cached handle."""
    path = Path(__file__).resolve().parents[1] / "tools" / "cc" / "mail.py"
    spec = importlib.util.spec_from_file_location("_mail_for_the_ruling_tests", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_mail_for_the_ruling_tests"] = module   # registered before exec (3.14)
    spec.loader.exec_module(module)
    return module


class TestARedBaseRuledByTheDispatcher:
    """A red no revert can clear (pytest 9.2.0 redded main outside every
    suspect's diff on 2026-10-29; every seat held eleven hours; the fix landed
    by a hand-opened pull request) has a way through the driver: `open` and
    `handoff` take --base-red-ruled <ack id>, and let the lane land when the
    dispatcher's ack with that id is on the local mail refs and names the red
    run by its id. The revert stays the default: without the flag the refusal
    names the way through, and with it every way the ruling does not hold
    refuses by name."""

    @staticmethod
    def _stand_in(ship, monkeypatch, by_machine: dict, *, dispatcher: str | None = "air",
                  how: str = "espalier.toml sets dispatcher = air") -> None:
        monkeypatch.setattr(ship, "_MAIL", None)
        real = ship._mail_module()
        unusable = real.DISPATCHER_UNUSABLE   # the real phrase: a stub that copied it would not drift
        if dispatcher == "unusable":
            dispatcher = unusable
        monkeypatch.setattr(ship, "_MAIL", _ruling_channel(by_machine, dispatcher=dispatcher, how=how,
                                                           unusable=unusable, real=real))

    def test_the_rulings_words_are_the_channels(self, ship):
        """The driver keeps the marker, the head and the text cap as literals
        (the channel is loaded on first use, and the refusal names the head
        where no ruling was given); the channel's reader is the rule. Dies
        to: either side's words changed alone."""
        mail = _real_mail()
        assert ship.RULING_PREFIX == mail.RULING_PREFIX == "gridlock:"
        assert ship.RULING_HEAD == mail.RULING_HEAD == "gridlock: fix forward run "
        assert ship.RULING_TEXT_CHARS == mail.RULING_TEXT_CHARS
        source = (Path(__file__).resolve().parents[1] / "tools" / "cc" / "ship.py").read_text(encoding="utf-8")
        assert "_RULING_HEAD_RE" not in source and "_MESSAGE_ID_RE" not in source, \
            "the driver grew a reader of its own beside the channel's"
        # By shape, not by name: no regex the driver builds or runs mentions the
        # ruling's words, under any name (the channel's reader is the one).
        import ast

        from tests._source_segment import segment, source_lines   # split once, slice per node (the suite's slicer)
        lines = source_lines(source)
        for node in ast.walk(ast.parse(source)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "re"
                    and node.func.attr in ("compile", "match", "search", "fullmatch")):
                text = segment(lines, node) or ""
                assert "RULING" not in text.upper(), f"the driver reads the ruling's words with a regex of its own: {text}"

    def test_a_mistyped_id_is_told_the_shape_before_the_channel_is_read(self, ship, tmp_path, monkeypatch):
        """The shape check runs before any read, as it did when the driver held
        the rule: a mistyped id on a tree whose channel cannot be read gets the
        shape, not the channel error, and costs no git read."""
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack("900")]})

        def torn(root, **kw):
            raise OSError("the refs are torn")

        monkeypatch.setattr(ship._MAIL, "read_mail", torn)
        for bad in ("ab12cd", "20261030T110000Z-air-work-0f0f0", "not an id"):
            sender, problem, text = ship.red_base_ruling(tmp_path, bad, "900", branch="lane/x")
            assert (sender, text) == ("", "") and problem.startswith(f"{bad} is not a message id"), problem
        sender, problem, text = ship.red_base_ruling(tmp_path, _RULING, "900", branch="lane/x")
        assert "the mail channel could not be read" in problem and "the refs are torn" in problem

    def test_an_older_channel_without_the_reader_is_named_not_raised(self, ship, tmp_path, monkeypatch):
        """An upgrade keeps an adopter's edited mail.py beside the new driver:
        the driver says the channel predates the reader instead of a traceback."""
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack("900")]})
        monkeypatch.delattr(ship._MAIL, "fix_forward_ruling")
        sender, problem, text = ship.red_base_ruling(tmp_path, _RULING, "900", branch="lane/x")
        assert (sender, text) == ("", "") and "predates the ruling reader (upgrade it)" in problem

    def test_a_revert_lane_on_a_ruled_run_is_told_the_merge_was_found_blameless(self, ship, tmp_path, forget_guard,
                                                                                  monkeypatch, capsys):
        """The route the defect's record names: a seat acting on an older read
        of the board claims revert/<sha> after the ruling, and the driver let
        it through without a word. It still lets it through (the revert-first
        rule), and says what the revert undoes. Dies to: silence."""
        _write_guard(tmp_path)
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack("900", lane="lane/x")]})
        spawns = _arm(ship, _open_answers(tmp_path, branch="revert/abc1234", base_runs=_RED_BASE))
        assert ship.open_pr() == 0
        assert spawns.count(("gh", "pr", "create")) == 1
        out = capsys.readouterr().out
        assert (f"the base's red run 900 was ruled a fix-forward by {_RULING} for lane/x: this revert undoes a "
                "merge that ruling found blameless") in out
        assert "make sure it is the dispatcher's call" in out
        # No ruling on the run: nothing said; the mail channel torn: said, and the revert goes on.
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack("950", lane="lane/x")]})
        _arm(ship, _open_answers(tmp_path, branch="revert/abc1234", base_runs=_RED_BASE))
        assert ship.open_pr() == 0 and "found blameless" not in capsys.readouterr().out
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack("900", lane="lane/x")]})

        def torn(root, **kw):
            raise OSError("the refs are torn")

        monkeypatch.setattr(ship._MAIL, "read_mail", torn)
        _arm(ship, _open_answers(tmp_path, branch="revert/abc1234", base_runs=_RED_BASE))
        assert ship.open_pr() == 0
        assert "was not checked for a ruling (the mail channel could not be read: the refs are torn)" in capsys.readouterr().out

    def test_the_refusal_names_the_ruling_as_the_way_through(self, ship, tmp_path, forget_guard):
        """Without the flag the refusal stands, and says what lets a ruled
        fix-forward through, by the run id the ack must name. Dies to: a
        refusal whose only way out is the revert (the eleven-hour hold)."""
        _write_guard(tmp_path)
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        text = str(stop.value)
        assert "Nothing lands on a red base" in text and "revert/" in text
        assert "--base-red-ruled <ack id>" in text and "run 900" in text
        assert spawns.mutations == []

    def test_preflight_names_the_ruling_as_the_way_through(self, ship, tmp_path, capsys):
        _memory(tmp_path, "2026-10-09")
        _arm(ship, _preflight_answers(tmp_path, base_runs=_RED_BASE))
        assert ship.preflight() == 0
        out = capsys.readouterr().out
        assert "`open` will refuse this lane: main red after merge" in out
        assert "--base-red-ruled <ack id>" in out and "run 900" in out

    def test_the_dispatchers_ack_naming_the_run_lets_the_lane_through(self, ship, tmp_path, forget_guard,
                                                                       monkeypatch, capsys):
        """The ruling on the record twice: said at the open, and in the pull
        request body every reader of the lane sees."""
        _write_guard(tmp_path)
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack("900")]})
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        assert ship.open_pr(base_red_ruled=_RULING) == 0
        assert spawns.count(("gh", "pr", "create")) == 1
        out = capsys.readouterr().out
        assert f"ruling {_RULING}" in out and "run 900" in out and "air" in out
        assert any(f"ruling {_RULING}" in body and "run 900" in body for body in spawns.body_texts), spawns.body_texts

    def test_no_such_ack_on_the_local_refs_refuses_by_name(self, ship, tmp_path, forget_guard, monkeypatch):
        _write_guard(tmp_path)
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack("900", ack_id="20261030T120000Z-air-000000")]})
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr(base_red_ruled=_RULING)
        text = str(stop.value)
        assert f"no ack {_RULING}" in text and "mail.py inbox" in text
        assert "Nothing lands on a red base" in text
        assert spawns.mutations == []

    def test_an_ack_on_another_seats_ref_does_not_rule(self, ship, tmp_path, forget_guard, monkeypatch):
        """The ref is the sender, never the message's from field: an ack on
        win's ref claiming to be air's is win's."""
        _write_guard(tmp_path)
        self._stand_in(ship, monkeypatch, {"win": [_ruling_ack("900", machine="air")]})
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr(base_red_ruled=_RULING)
        text = str(stop.value)
        assert "win's ref" in text and "dispatcher's (air)" in text
        assert spawns.mutations == []

    def test_an_ack_naming_another_run_does_not_rule(self, ship, tmp_path, forget_guard, monkeypatch):
        """A ruling on an older red does not let a newer one through, and a
        run id is matched whole: 9001 does not name 900."""
        _write_guard(tmp_path)
        for other in ("800", "9001"):
            self._stand_in(ship, monkeypatch, {"air": [_ruling_ack(other)]})
            spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
            with pytest.raises(ship.Refused) as stop:
                ship.open_pr(base_red_ruled=_RULING)
            assert f"rules on run {other}, not the base's red run 900" in str(stop.value), (other, str(stop.value))
            assert spawns.mutations == []

    def test_with_no_dispatcher_named_any_seats_ack_rules(self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        """A lone operator's default, the fold's own rule for assigns."""
        _write_guard(tmp_path)
        self._stand_in(ship, monkeypatch, {"win": [_ruling_ack("900", machine="win")]}, dispatcher=None,
                       how="espalier.toml does not set dispatcher, so every machine's assigns count")
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        assert ship.open_pr(base_red_ruled=_RULING) == 0
        assert spawns.count(("gh", "pr", "create")) == 1
        assert "win" in capsys.readouterr().out

    def test_an_unusable_dispatcher_setting_refuses_by_name(self, ship, tmp_path, forget_guard, monkeypatch):
        """A broken team setting fails closed, as it does for assigns."""
        _write_guard(tmp_path)
        how = ("espalier.toml sets dispatcher = Air, which is not a machine name (lowercase letters, digits "
               "and hyphens), so no assign counts until it is")
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack("900")]}, dispatcher="unusable", how=how)
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr(base_red_ruled=_RULING)
        assert "not a machine name" in str(stop.value)
        assert spawns.mutations == []

    def test_no_mail_channel_refuses_by_name(self, ship, tmp_path, forget_guard, monkeypatch):
        _write_guard(tmp_path)
        monkeypatch.setattr(ship, "_mail_module", lambda: None)
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr(base_red_ruled=_RULING)
        assert "mail.py is not beside this script" in str(stop.value)
        assert spawns.mutations == []

    def test_a_green_base_with_the_flag_notes_and_opens(self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        _write_guard(tmp_path)
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack("900")]})
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr(base_red_ruled=_RULING) == 0
        assert spawns.count(("gh", "pr", "create")) == 1
        out = capsys.readouterr().out
        assert "not red" in out and _RULING in out
        assert not any(_RULING in body for body in spawns.body_texts)   # no ruling was used: none on the record

    def test_a_handoff_with_the_ruling_lands_the_lane_and_arms_without_a_held_refusal(
            self, ship, tmp_path, forget_guard, monkeypatch):
        """The no-pull-request path: the handoff's open takes the ruling, the
        push runs, and the own-clear arms as after any landed handoff."""
        answers = TestTheHandoffArmsTheOwnClear()._red_base_answers(tmp_path)
        calls = TestTheHandoffArmsTheOwnClear._arm_calls(ship, monkeypatch)
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack("900")]})
        spawns = _arm(ship, answers)
        assert ship.handoff(base_red_ruled=_RULING) == 0
        assert spawns.count(("git", "push")) == 1
        assert calls == [{}], calls

    def test_a_handoff_onto_an_armed_pull_request_names_the_ruling_not_the_disarm(
            self, ship, tmp_path, monkeypatch, capsys):
        _toml(tmp_path, "handoff_push = true\n")
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack("900")]})
        _arm(ship, TestHandoffVerb._existing_pr_answers(tmp_path, base_runs=_RED_BASE))
        monkeypatch.setattr(ship, "rebind", lambda dry_run=False: 0)
        assert ship.handoff(base_red_ruled=_RULING) == 0
        out = capsys.readouterr().out
        assert f"ruling {_RULING}" in out and "run 900" in out
        assert "disable-auto" not in out

    def test_a_handoff_onto_an_armed_pull_request_with_a_ruling_that_does_not_hold_names_both(
            self, ship, tmp_path, monkeypatch, capsys):
        _toml(tmp_path, "handoff_push = true\n")
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack("800")]})
        _arm(ship, TestHandoffVerb._existing_pr_answers(tmp_path, base_runs=_RED_BASE))
        monkeypatch.setattr(ship, "rebind", lambda dry_run=False: 0)
        assert ship.handoff(base_red_ruled=_RULING) == 0   # the row still reaches the pull request
        out = capsys.readouterr().out
        assert "rules on run 800, not the base's red run 900" in out and "gh pr merge --disable-auto 7" in out

    def test_main_parses_the_flag_on_open_and_handoff(self, ship, monkeypatch):
        seen: list[tuple[str, dict]] = []
        monkeypatch.setattr(ship, "open_pr", lambda **kw: seen.append(("open", kw)) or 0)
        monkeypatch.setattr(ship, "handoff", lambda **kw: seen.append(("handoff", kw)) or 0)
        assert ship.main(["open", "--base-red-ruled", _RULING]) == 0
        assert ship.main(["handoff", "--base-red-ruled", _RULING]) == 0
        assert [(verb, kw["base_red_ruled"]) for verb, kw in seen] == [("open", _RULING), ("handoff", _RULING)]
        seen.clear()
        assert ship.main(["open"]) == 0 and seen[0][1]["base_red_ruled"] is None

    def test_an_ack_without_the_fixed_head_does_not_rule(self, ship, tmp_path, forget_guard, monkeypatch):
        """A status, a veto or a hold that names the run is not a ruling, under
        the gridlock: marker or not: the marker carries no direction, so the
        driver reads the way the ruling went from the fixed head alone. Dies
        to: any dispatcher ack naming the run read as a ruling (the failure-mode
        review drove 'do NOT fix forward on run 900' through), or any gridlock:
        ack naming it (the dispatcher's redirect drove 'gridlock: run 900 is
        red ...; do NOT fix forward yet' through the marker rule)."""
        _write_guard(tmp_path)
        for text in ("seen: run 900 is red; every lane holds", "do NOT fix forward on run 900; revert first",
                     "gridlock: run 900 is red outside #352's diff; do NOT fix forward yet, every seat holds",
                     "RULING re f242ff: (a) fix forward on run 900, the operator's word"):
            self._stand_in(ship, monkeypatch, {"air": [_ruling_ack(text=text)]})
            spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
            with pytest.raises(ship.Refused) as stop:
                ship.open_pr(base_red_ruled=_RULING)
            assert "does not open with the head `gridlock: fix forward run <run id>`" in str(stop.value), str(stop.value)
            assert spawns.mutations == []

    def test_a_request_with_the_id_is_not_a_ruling(self, ship, tmp_path, forget_guard, monkeypatch):
        """The operator call that lists the run is the question; its answer is the ruling."""
        _write_guard(tmp_path)
        call = "OPERATOR CALL: run 900 is red outside every suspect's diff; (a) fix forward (b) revert"
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack(kind="request", text=call)]})
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr(base_red_ruled=_RULING)
        assert "is a request, not an ack" in str(stop.value)
        assert spawns.mutations == []

    def test_an_id_of_another_shape_is_told_the_shape(self, ship, tmp_path, forget_guard, monkeypatch):
        """Seats name messages by their 6-character tail in prose; the flag takes the full id."""
        _write_guard(tmp_path)
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack()]})
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr(base_red_ruled="ab12cd")
        assert "ab12cd is not a message id" in str(stop.value) and "full id" in str(stop.value)
        assert spawns.mutations == []

    def test_a_ruling_naming_no_run_says_so(self, ship, tmp_path, forget_guard, monkeypatch):
        """The 2026-10-29 ruling named its run only through the call it answered."""
        _write_guard(tmp_path)
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack(text="gridlock: (a) fix-forward, the operator's "
                                                                     "word at 01:30Z; no revert")]})
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr(base_red_ruled=_RULING)
        text = str(stop.value)
        assert "does not open with the head" in text and "rules nothing" in text
        assert spawns.mutations == []

    def test_a_mail_channel_that_cannot_be_read_refuses_by_name(self, ship, tmp_path, forget_guard, monkeypatch):
        """Never a traceback past main, and never a handoff whose arm is skipped."""
        _write_guard(tmp_path)
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack()]})

        def boom(root, **kw):
            raise TimeoutError("git for-each-ref took longer than 30s")

        ship._MAIL.read_mail = boom
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr(base_red_ruled=_RULING)
        assert "mail channel could not be read" in str(stop.value)
        assert spawns.mutations == []

    def test_the_dispatchers_own_ack_rules_over_a_same_id_ack_on_another_ref(
            self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        """A stray same-id message on a ref that sorts first does not block the dispatcher's own."""
        _write_guard(tmp_path)
        self._stand_in(ship, monkeypatch, {"aaa": [_ruling_ack(text="seen: run 900", machine="aaa")],
                                           "air": [_ruling_ack()]})
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        assert ship.open_pr(base_red_ruled=_RULING) == 0
        assert spawns.count(("gh", "pr", "create")) == 1
        assert "air's gridlock ack" in capsys.readouterr().out

    def test_a_ruling_for_another_lane_does_not_rule_this_one(self, ship, tmp_path, forget_guard, monkeypatch):
        """Core Rule 15 says the FIX lane lands; an ack naming a lane rules for it alone."""
        _write_guard(tmp_path)
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack(lane="lane/the-fix")]})
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr(base_red_ruled=_RULING)
        assert "rules for lane/the-fix, not this lane (lane/x)" in str(stop.value)
        assert spawns.mutations == []
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack(lane="")]})
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr(base_red_ruled=_RULING)
        assert "names no lane" in str(stop.value) and "--lane" in str(stop.value)
        assert spawns.mutations == []
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack(lane="lane/x")]})
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        assert ship.open_pr(base_red_ruled=_RULING) == 0

    def test_the_rulings_text_rides_the_terminal_and_the_body(self, ship, tmp_path, forget_guard, monkeypatch,
                                                              capsys):
        _write_guard(tmp_path)
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack()]})
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        assert ship.open_pr(base_red_ruled=_RULING) == 0
        assert "gridlock: fix forward" in capsys.readouterr().out
        assert any("Landed on a red base by ruling:" in body and "gridlock: fix forward" in body
                   for body in spawns.body_texts), spawns.body_texts

    def test_a_dry_run_with_the_ruling_says_it_and_touches_nothing(self, ship, tmp_path, forget_guard, monkeypatch,
                                                                   capsys):
        _write_guard(tmp_path)
        self._stand_in(ship, monkeypatch, {"air": [_ruling_ack()]})
        spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
        assert ship.open_pr(base_red_ruled=_RULING, dry_run=True) == 0
        assert f"ruling {_RULING}" in capsys.readouterr().out
        assert spawns.mutations == []

    def test_a_revert_lane_notes_a_flag_it_did_not_read(self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        _write_guard(tmp_path)
        monkeypatch.setattr(ship, "_mail_module", lambda: None)   # never read: a revert/ lane asks no ruling
        spawns = _arm(ship, _open_answers(tmp_path, branch="revert/abc1234", base_runs=_RED_BASE))
        assert ship.open_pr(base_red_ruled=_RULING) == 0
        assert spawns.count(("gh", "pr", "create")) == 1
        assert "needs no ruling" in capsys.readouterr().out

    def test_the_run_id_is_matched_whole_on_both_sides(self, ship, tmp_path, forget_guard, monkeypatch):
        _write_guard(tmp_path)
        for other in ("1900", "9001"):
            self._stand_in(ship, monkeypatch, {"air": [_ruling_ack(other)]})
            spawns = _arm(ship, _open_answers(tmp_path, base_runs=_RED_BASE))
            with pytest.raises(ship.Refused) as stop:
                ship.open_pr(base_red_ruled=_RULING)
            text = str(stop.value)
            assert f"rules on run {other}, not the base's red run 900" in text, text
            assert spawns.mutations == []

    def test_the_ruling_marker_is_the_census_marker_and_the_brief_names_the_flag(self, ship):
        """One word across the driver, the census's table and the dispatcher's
        brief; and the brief tells the dispatcher to name the run and the flag."""
        root = Path(__file__).resolve().parents[1]
        census = (root / "scripts" / "seat_day_census.py").read_text(encoding="utf-8")
        assert f'"gridlock": "{ship.RULING_PREFIX}"' in census
        spec = importlib.util.spec_from_file_location("_seat_for_the_ruling_test", root / "tools" / "cc" / "seat.py")
        seat = importlib.util.module_from_spec(spec)
        sys.modules["_seat_for_the_ruling_test"] = seat   # registered before exec (3.14)
        spec.loader.exec_module(seat)
        brief = seat.SELF_HOST_GRIDLOCK   # the composed sentence, not the source's line-broken literals
        assert f"opens with the fixed head {ship.RULING_HEAD}<the red post-merge run's id>" in brief
        assert f"open {ship.BASE_RED_RULED_FLAG} <that ack's full id>" in brief


class TestTheRedBaseReadsTheBoardsWindow:
    """DEF-2018: each push's post-merge proof runs to the end beside the next
    (DEF-2015), so a burst of merges holds several runs still going above the
    newest verdict. The read took five runs while the board took twenty, and five
    still going hid a red the board named: `open` armed over it."""

    @staticmethod
    def _gh_by_limit(rows: list[dict]):
        """`gh run list` as gh answers it: at most `--limit` rows, newest first."""
        def gh_json(*args, **_kwargs):
            return rows[:int(args[list(args).index("--limit") + 1])]
        return gh_json

    def test_a_burst_of_runs_still_going_cannot_hide_a_red(self, ship, monkeypatch):
        """Dies to: a window shorter than the burst (the five this read took)."""
        red = {"status": "completed", "conclusion": "failure", "headSha": "a" * 40, "databaseId": 905,
               "url": "https://example/run/905"}
        monkeypatch.setattr(ship, "_gh_json", self._gh_by_limit([{"status": "in_progress", "conclusion": ""}] * 5
                                                                + [red]))
        line = ship.base_red_after_merge("main")
        assert line is not None and "main red after merge: post-merge.yml run 905 on aaaaaaa" in line, line

    def test_the_window_is_the_boards(self, ship, monkeypatch):
        """One window, not two hand numbers, as the red set is one set (that pin
        is tests/test_board.py's)."""
        spec = importlib.util.spec_from_file_location("board_for_ship_test", SHIP.parent / "board.py")
        board = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, board)
        spec.loader.exec_module(board)
        assert ship.POST_MERGE_RUN_WINDOW == board.RUN_WINDOW


class TestOneOpenPullRequestPerSeat:
    """`open` holds a lane while this seat has another pull request open, by
    the seat whose latest claim or release names each lane: every seat may push
    as one GitHub account, so the author cannot tell them apart. DEF-5038: the
    Stop hook's handoff gate held a finished second lane (DEF-4058), and any
    forced handoff -- the threshold ask, the operator's end-of-day /handoff --
    ran `open`, which only noted the first and opened the second beside it."""

    @staticmethod
    def _channel(seat: str, lanes: dict[str, str]):
        return types.SimpleNamespace(
            machine_setting=lambda root, **kw: (seat, "stubbed"),
            read_mail=lambda root, **kw: ({}, {}),
            lane_seats=lambda by_machine: dict(lanes),
            release_lane=lambda root, lane, text="", **kw: None)

    _OTHERS = json.dumps([{"number": 41, "headRefName": "lane/y", "autoMergeRequest": {"x": 1}},
                          {"number": 42, "headRefName": "lane/z", "autoMergeRequest": {"x": 1}}])
    #: The lane's upstream, as the Stop hook's handoff gate reads it.
    _UPSTREAM = ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    _NO_UPSTREAM = (128, "", "fatal: no upstream configured for branch 'lane/x'\n")

    def _held_answers(self, ship, tmp_path, monkeypatch, upstream=_NO_UPSTREAM, branch="lane/x") -> dict:
        _write_guard(tmp_path)
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", {"lane/y": "win", "lane/z": "air", branch: "win"}))
        answers = _open_answers(tmp_path, open_prs=self._OTHERS, branch=branch)
        answers[self._UPSTREAM] = upstream
        return answers

    def test_open_holds_a_lane_never_pushed_while_this_seats_other_one_is_open(
            self, ship, tmp_path, forget_guard, monkeypatch):
        """Dies to: the note alone (the unfixed driver opens #43 beside #41),
        or a hold that pushes first."""
        spawns = _arm(ship, self._held_answers(ship, tmp_path, monkeypatch))
        with pytest.raises(ship.Held) as stop:
            ship.open_pr()
        held = stop.value
        assert held.landed is False and held.waits_for == "#41 merges or closes"
        text = str(held)
        assert "this seat (win) already has an open pull request: #41 (lane/y)" in text
        assert "opened once #41 merges or closes" in text and "#42" not in text
        assert "git push -u origin HEAD" in text   # the named way past a wrong attribution
        assert text.isascii()
        assert spawns.mutations == []   # nothing pushed, nothing created
        # Held before the base is fetched, merged in or folded: nothing of the
        # lane's shape moves under a hold.
        assert spawns.count(("git", "fetch", "origin", "main")) == 0
        assert spawns.count(("git", "merge-tree")) == 0

    def test_the_hold_writes_the_stop_gates_own_hold_record(self, ship, tmp_path, forget_guard, monkeypatch):
        """The failure-mode review, 2026-11-01: a handoff held here arms the
        own-clear at this HEAD, so the gate wrote no hold, and the next
        SessionStart seeded its flag past the lane: nothing asked for it once
        the window was cleared. Dies to: the hold left to the brief alone."""
        _arm(ship, self._held_answers(ship, tmp_path, monkeypatch))
        with pytest.raises(ship.Held):
            ship.open_pr()
        gate = ship._paths.hooks_module("stop_gate")
        hold = gate._hold_read(tmp_path)
        assert hold is not None and hold["head"] == HEAD and hold["branch"] == "lane/x"
        assert hold["prs"] == ["#41 (lane/y)"] and hold["seat"] == "win"
        seed = ship._paths.hooks_module("session_start")
        assert seed._hold_names(tmp_path / gate.STATE_DIR / gate.HANDOFF_GATE_HOLD, HEAD)

    def test_a_dry_run_holds_and_writes_no_record(self, ship, tmp_path, forget_guard, monkeypatch):
        _arm(ship, self._held_answers(ship, tmp_path, monkeypatch))
        with pytest.raises(ship.Held):
            ship.open_pr(dry_run=True)
        assert ship._paths.hooks_module("stop_gate")._hold_read(tmp_path) is None

    def test_two_of_this_seats_pull_requests_open_name_both(self, ship, tmp_path, forget_guard, monkeypatch):
        answers = self._held_answers(ship, tmp_path, monkeypatch)
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", {"lane/y": "win", "lane/z": "win"}))
        _arm(ship, answers)
        with pytest.raises(ship.Held) as stop:
            ship.open_pr()
        assert stop.value.waits_for == "#41, #42 merge or close"

    def test_a_red_base_refuses_before_the_hold(self, ship, tmp_path, forget_guard, monkeypatch):
        """The red base's refusal names the revert and the disarms; the hold
        would hide them. Dies to: the hold read before the base."""
        answers = self._held_answers(ship, tmp_path, monkeypatch)
        answers[("gh", "run", "list", "--workflow", "post-merge.yml")] = (0, _RED_BASE, "")
        _arm(ship, answers)
        with pytest.raises(ship.Held) as stop:
            ship.open_pr()
        assert "Nothing lands on a red base" in str(stop.value) and stop.value.waits_for == ""

    def test_a_lane_with_no_row_refuses_before_the_hold(self, ship, tmp_path, forget_guard, monkeypatch):
        """The row is the window's to write first: the hold promises the next
        window a row written. Dies to: the hold read before the row."""
        _toml(tmp_path, "handoff_push = true\n")
        answers = self._held_answers(ship, tmp_path, monkeypatch)
        answers[_MEMORY_LOG] = (0, "", "")
        _arm(ship, answers)
        with pytest.raises(ship.Refused) as stop:
            ship.open_pr()
        assert not isinstance(stop.value, ship.Held)

    def test_a_lane_tracking_the_base_is_not_its_own_upstream_and_is_held(
            self, ship, tmp_path, forget_guard, monkeypatch):
        """A branch started from origin/main tracks origin/main by git's
        default: an upstream, but not the lane's own, so the push would open a
        pull request (the gate's rule, stop_gate._unpushed_commits)."""
        spawns = _arm(ship, self._held_answers(ship, tmp_path, monkeypatch, upstream=(0, "origin/main\n", "")))
        with pytest.raises(ship.Held):
            ship.open_pr()
        assert spawns.mutations == []

    def test_a_lane_with_an_upstream_of_its_own_opens_beside_with_the_note(
            self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        """Its push already landed once (a create that refused after it): the
        row's shape holds only a lane that was never pushed."""
        spawns = _arm(ship, self._held_answers(ship, tmp_path, monkeypatch, upstream=(0, "origin/lane/x\n", "")))
        assert ship.open_pr() == 0
        out = capsys.readouterr().out
        assert "this seat (win) already has an open pull request: #41 (lane/y)" in out
        assert "#42" not in out
        assert spawns.count(("gh", "pr", "create")) == 1

    def test_a_revert_lane_is_never_held(self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        """Core Rule 15: the revert lands first. Dies to: the hold read before
        the branch's prefix."""
        spawns = _arm(ship, self._held_answers(ship, tmp_path, monkeypatch, branch="revert/abc1234"))
        assert ship.open_pr() == 0
        assert spawns.count(("gh", "pr", "create")) == 1
        assert spawns.count(self._UPSTREAM) == 0
        out = capsys.readouterr().out
        assert "#41 (lane/y)" in out and "lands first" in out

    def test_a_lane_the_dispatchers_ruling_lets_onto_a_red_base_is_never_held(
            self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        """The fix the ruling names clears the red that holds this seat's other
        pull request (its armed auto-merge waits on the base), so holding the
        fix behind it is a deadlock."""
        monkeypatch.setattr(ship, "red_base_verdict", lambda *a, **kw: (None, "main red -- let through by ruling X"))
        spawns = _arm(ship, self._held_answers(ship, tmp_path, monkeypatch))
        assert ship.open_pr() == 0
        assert spawns.count(("gh", "pr", "create")) == 1
        assert "lands first" in capsys.readouterr().out

    def test_an_unread_open_pull_request_list_is_said_and_the_lane_opens(
            self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        """Never a hold on a guess, never silence: before this the check was
        skipped without a word when gh could not list."""
        _write_guard(tmp_path)
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", {"lane/y": "win"}))
        answers = _open_answers(tmp_path)
        answers[("gh", "pr", "list", "--state", "open")] = (1, "", "HTTP 502\n")
        spawns = _arm(ship, answers)
        assert ship.open_pr() == 0
        assert spawns.count(("gh", "pr", "create")) == 1
        out = capsys.readouterr().out
        assert "open pull requests could not be read" in out and "were not checked" in out

    def test_a_handoff_on_the_held_lane_arms_the_own_clear_with_the_hold(
            self, ship, tmp_path, forget_guard, monkeypatch):
        """The forced handoff the row names: its row written, the tree clean,
        no pull request for the lane; the marker carries the hold and the lane
        stays here. Dies to: the handoff opening the second pull request."""
        _toml(tmp_path, "handoff_push = true\n")
        answers = self._held_answers(ship, tmp_path, monkeypatch)
        answers[("git", "status", "--porcelain", "-uno")] = (0, "", "")
        answers[_MEMORY_LOG] = (0, "abc1234\n", "")
        answers[_list_key()] = [(0, "[]", ""), (0, "[]", "")]
        spawns = _arm(ship, answers)
        calls = TestTheHandoffArmsTheOwnClear._arm_calls(ship, monkeypatch)
        with pytest.raises(ship.Held, match="opened once #41 merges or closes"):
            ship.handoff()
        assert spawns.mutations == []
        assert calls and calls[0]["held"].landed is False and calls[0]["held"].waits_for == "#41 merges or closes"

    def test_another_seats_pull_requests_say_nothing(self, ship, tmp_path, forget_guard, monkeypatch, capsys):
        _write_guard(tmp_path)
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", {"lane/y": "air", "lane/z": "win-2"}))
        _arm(ship, _open_answers(tmp_path, open_prs=self._OTHERS))
        assert ship.open_pr() == 0
        assert "already has an open pull request" not in capsys.readouterr().out

    def test_a_pull_request_no_claim_names_is_this_seats_by_its_label(self, ship, tmp_path, monkeypatch):
        """DEF-4044: the seat label the driver stamps names a lane no claim
        does, for the one-per-seat advisory as for the records line; a claim
        still wins. Dies to: the label ignored here (a sister site of the
        records read), or read over a claim."""
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", {"lane/z": "air"}))
        others = [{"number": 41, "headRefName": "lane/y", "autoMergeRequest": None, "labels": [{"name": "seat:win"}]},
                  {"number": 42, "headRefName": "lane/z", "autoMergeRequest": None, "labels": [{"name": "seat:win"}]},
                  {"number": 43, "headRefName": "lane/w", "autoMergeRequest": None, "labels": [{"name": "seat:air"}]}]
        assert ship.seat_open_prs(tmp_path, "lane/x", others) == ("win", ["#41 (lane/y)"])

    def test_seat_name_is_the_one_reader_for_the_gate_and_the_advisory(self, ship, tmp_path, monkeypatch):
        """DEF-4058: the Stop hook's handoff gate reads the seat's name before
        any gh spawn through this reader, and the one-per-seat advisory reads
        it the same way. An unset name is ("", ""), as is a tree without the
        channel; the channel's unread phrase is the problem, nothing else is."""
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", {"lane/y": "win"}))
        assert ship.seat_name(tmp_path) == ("win", "")
        assert ship.seat_name(tmp_path, timeout=2.0) == ("win", "")
        channel = self._channel("", {})
        channel.MACHINE_UNREAD = "the machine name could not be read"
        channel.machine_setting = lambda root, **kw: (
            "", "the machine name could not be read (git config took longer than 2s)")
        monkeypatch.setattr(ship, "_MAIL", channel)
        name, problem = ship.seat_name(tmp_path)
        assert name == "" and problem.startswith("the machine name could not be read")
        channel.machine_setting = lambda root, **kw: ("", "git config espalier.machine is not set")
        assert ship.seat_name(tmp_path) == ("", "")

    def test_an_unread_seat_name_is_said_never_read_as_no_seat(self, ship, tmp_path, forget_guard, monkeypatch,
                                                              capsys):
        """A name read that failed (a timeout, a config git cannot parse) is not
        an unnamed box: the one-per-seat check was skipped in silence, so a
        seat's second open pull request opened unremarked. Still an advisory:
        the lane opens. Dies to: the unread reason taken for an unset name."""
        _write_guard(tmp_path)
        monkeypatch.setattr(ship, "_MAIL", None)
        phrase = ship._mail_module().MACHINE_UNREAD   # the real one: a stub that copied it would not drift
        channel = self._channel("win", {"lane/y": "win"})
        channel.MACHINE_UNREAD = phrase
        channel.machine_setting = lambda root, **kw: (
            None, f"{phrase} (git config took longer than 10s), so no machine is named")
        monkeypatch.setattr(ship, "_MAIL", channel)
        spawns = _arm(ship, _open_answers(tmp_path, open_prs=self._OTHERS))
        assert ship.open_pr() == 0
        out = capsys.readouterr().out
        assert "machine name could not be read" in out and "took longer than 10s" in out, out
        assert "open pull requests were not checked" in out
        assert spawns.count(("gh", "pr", "create")) == 1
        channel.machine_setting = lambda root, **kw: (None, "git config espalier.machine is not set")
        assert ship.seat_open_prs(tmp_path, "lane/x", json.loads(self._OTHERS)) == ("", [])
        assert "could not be read" not in capsys.readouterr().out   # an unset name stays silent


class TestSeatRowDebt:
    """The Session Log debt the board's `records:` line prints and `open
    --early` will refuse on (the second lane): this seat's lanes merged, in
    the writer's local day, after its newest row on the BASE's tree. No
    verdict is never a refusal on a guess: git, gh or the channel failing
    reads as None, never as zero."""

    _NAMES = ("memory/session-log.d/2026-10-15-073941-win.md\n"
              "memory/session-log.d/2026-10-18-163553-win.md\n"
              "memory/session-log.d/2026-10-19-053029-air.md\n")
    # Noon UTC: the same local day in every zone a seat runs in.
    _MERGED = json.dumps([{"number": 1, "headRefName": "lane/a", "mergedAt": "2026-10-18T12:00:00Z"},
                          {"number": 2, "headRefName": "lane/b", "mergedAt": "2026-10-19T12:00:00Z"},
                          {"number": 3, "headRefName": "lane/c", "mergedAt": "2026-10-20T12:00:00Z"},
                          {"number": 4, "headRefName": "lane/d", "mergedAt": "2026-10-20T12:00:00Z"}])
    _LANES = {"lane/a": "win", "lane/b": "win", "lane/c": "win", "lane/d": "air"}

    @staticmethod
    def _channel(seat, lanes, parked=(), pending_error=None):
        def pending(root, directory, against, **kw):
            if pending_error:
                raise RuntimeError(pending_error)
            assert directory.rstrip("/") == "memory/session-log.d" and against == ["origin/main"], (directory, against)
            # The fold trailer rides every pending read (DEF-4045): a reader that drops it falls back to the first rule.
            assert kw.get("trailer") == "Espalier-Fold: session-log", kw
            return [(seat, path, f"refs/remotes/origin/records/{seat}") for path in parked]
        return types.SimpleNamespace(
            machine_setting=lambda root, **kw: (seat, "stubbed"),
            read_mail=lambda root, **kw: ({"win": []}, {}),
            lane_seats=lambda by_machine: dict(lanes),
            pending=pending)

    #: The base's history read of the Session Log names its prunes deleted (the loader's one argv).
    _PRUNED = ("git", "log", "--format=%x1e%(trailers:key=Espalier-Fold,valueonly)%x1f", "--name-only")

    @staticmethod
    def _pruned_log(*commits: tuple[str, list[str]]) -> str:
        """The history read's answer: ``(fold trailer value or "", deleted paths)`` per commit, newest first."""
        return "".join(f"\x1e{value}\n\x1f\n" + "".join(f"{p}\n" for p in paths) for value, paths in commits)

    def _answers(self, names=_NAMES, merged=_MERGED, tree_rc=0, gh_rc=0, pruned="", shallow="false\n"):
        return {("git", "ls-tree"): (tree_rc, names if tree_rc == 0 else "", "fatal: not a tree" if tree_rc else ""),
                ("git", "rev-parse", "--is-shallow-repository"): (0, shallow, ""),
                self._PRUNED: (0, pruned, ""),
                ("gh", "pr", "list"): (gh_rc, merged if gh_rc == 0 else "", "gh: not logged in" if gh_rc else "")}

    def test_the_debt_is_the_seats_lanes_merged_after_its_newest_row_on_the_base(self, ship, tmp_path, monkeypatch):
        """Dies to: the names read from the working tree (a seat can edit it),
        the window read as POST_MERGE_ROWS, or a second merged read outside
        _post_merge.read_merged."""
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", self._LANES))
        spawns = _arm(ship, self._answers())
        assert ship.seat_row_debt(tmp_path, "main") == (2, "2026-10-18", "base")
        tree = spawns.matching(("git", "ls-tree"))
        assert len(tree) == 1 and "origin/main" in tree[0] and ship.SESSION_LOG_DIR in tree[0]
        reads = spawns.matching(("gh", "pr", "list"))
        fragments = ship._fragments_module()
        assert len(reads) == 1 and "--state" in reads[0] and "merged" in reads[0]
        assert reads[0][reads[0].index("--limit") + 1] == str(fragments.ROW_DEBT_WINDOW)
        assert "headRefName" in reads[0][reads[0].index("--json") + 1]
        assert "labels" in reads[0][reads[0].index("--json") + 1]
        pruned = spawns.matching(self._PRUNED)
        assert len(pruned) == 1 and pruned[0][1:] == fragments.pruned_rows_argv("origin/main")
        assert spawns.mutations == []

    def test_a_row_parked_on_the_seats_records_ref_is_its_newest_and_said_so(self, ship, tmp_path, monkeypatch):
        """A handoff whose lane already merged parks its row; open's early arm
        runs before the fold brings it in, so the reader must count it or a
        seat that wrote its row is refused. Dies to: the parked row ignored."""
        parked = ["memory/session-log.d/2026-10-19-210000-win.md"]
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", self._LANES, parked=parked))
        _arm(ship, self._answers())
        assert ship.seat_row_debt(tmp_path, "main") == (1, "2026-10-19", "parked")

    def test_a_seat_with_no_row_counts_every_lane_and_says_it_has_none(self, ship, tmp_path, monkeypatch):
        monkeypatch.setattr(ship, "_MAIL", self._channel("win-2", {"lane/a": "win-2", "lane/b": "win-2"}))
        _arm(ship, self._answers())
        assert ship.seat_row_debt(tmp_path, "main") == (2, "", "")

    def test_a_row_the_base_pruned_is_still_the_seats_newest_and_said_pruned(self, ship, tmp_path, monkeypatch):
        """#354's prune took win's newest row off origin/main (2026-10-30), and
        with no row on the base every lane in the window counted: 24+, where
        the seat had rowed every one. The names the fold's prunes deleted are
        read from the base's history beside the tree; a row deleted by a commit
        without the fold trailer (a revert, a hand prune) still counts as debt
        (the dispatcher's two named mutations, 2026-10-30). A shallow clone's
        history is cut and reads as unread, never as no pruned rows. Dies to:
        the history read dropped, an older pruned row read over the base's
        newest, a deletion without the trailer read as the seat's row, or a
        cut history read as none."""
        names = "memory/session-log.d/2026-10-19-053029-air.md\n"
        pruned = self._pruned_log(
            ("", ["memory/session-log.d/2026-10-21-120000-win.md"]),                 # a revert: no trailer, no row
            ("session-log", ["memory/session-log.d/2026-10-18-165314-win.md",
                             "memory/session-log.d/2026-10-10-120000-air.md"]),
            ("session-log", ["memory/session-log.d/2026-10-15-073941-win.md"]))
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", self._LANES))
        _arm(ship, self._answers(names=names, pruned=pruned))
        assert ship.seat_row_debt(tmp_path, "main") == (2, "2026-10-18", "pruned")
        monkeypatch.setattr(ship, "_MAIL", self._channel("air", self._LANES))
        _arm(ship, self._answers(names=names, pruned=pruned))
        assert ship.seat_row_debt(tmp_path, "main") == (1, "2026-10-19", "base")
        answers = self._answers(names=names, pruned=pruned)
        answers[self._PRUNED] = (128, "", "fatal: bad revision 'origin/main'")
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", self._LANES))
        _arm(ship, answers)
        assert ship.seat_row_debt(tmp_path, "main") is None   # an unread history is unread, never no pruned rows
        spawns = _arm(ship, self._answers(names=names, pruned="", shallow="true\n"))
        assert ship.seat_row_debt(tmp_path, "main") is None   # a shallow clone lists no prunes: unread, never none
        assert spawns.count(self._PRUNED) == 0 and spawns.count(("gh", "pr", "list")) == 0

    def test_a_lane_no_claim_names_counts_by_the_seat_label_on_its_pull_request(self, ship, tmp_path, monkeypatch):
        """DEF-4044: a merged lane no claim names was nobody's, so the cap was
        passed by not claiming; the seat:<name> label open stamps names it.
        Dies to: the label ignored, or read over a claim."""
        merged = json.loads(self._MERGED) + [
            {"number": 5, "headRefName": "lane/u", "mergedAt": "2026-10-20T12:00:00Z", "labels": [{"name": "seat:win"}]},
            {"number": 6, "headRefName": "lane/d", "mergedAt": "2026-10-21T12:00:00Z", "labels": [{"name": "seat:win"}]}]
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", self._LANES))
        _arm(ship, self._answers(merged=json.dumps(merged)))
        assert ship.seat_row_debt(tmp_path, "main") == (3, "2026-10-18", "base")   # lane/d is air's by claim

    def test_a_row_riding_the_seats_own_open_pull_request_is_its_newest(self, ship, tmp_path, monkeypatch):
        """A row on the seat's other open pull request is written and waits
        for its merge: neither on the base nor parked (the first lane's
        failure-mode review). Its head is fetched by object id and read by
        name; another seat's open pull request is not read. Dies to: the open
        heads ignored, or a head that could not be fetched read as no rows."""
        prs = [{"number": 9, "headRefName": "lane/open", "headRefOid": "feedface" * 5, "labels": []},
               {"number": 10, "headRefName": "lane/theirs", "headRefOid": "0badf00d" * 5, "labels": []}]
        lanes = dict(self._LANES, **{"lane/open": "win", "lane/theirs": "air"})
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", lanes))
        answers = self._answers()
        answers[("git", "fetch", "origin", "feedface" * 5)] = (0, "", "")
        # The head carries the base's fragments as of its branch point too: air's row there is not win's riding row.
        answers[("git", "ls-tree", "--name-only", "feedface" * 5)] = (
            0, "memory/session-log.d/2026-10-21-120000-win.md\nmemory/session-log.d/2026-10-22-120000-air.md\n", "")
        spawns = _arm(ship, answers)
        reading = ship._row_debt_reading(tmp_path, "main", prs)
        assert (reading["count"], reading["since"], reading["where"]) == (0, "2026-10-21", "open")
        assert reading["newest"].get("air") == ("2026-10-19", "base"), reading["newest"]
        assert spawns.count(("git", "fetch")) == 1 and "0badf00d" * 5 not in " ".join(spawns.matching(("git", "fetch"))[0])
        assert spawns.count(("git", "ls-tree", "--name-only", "0badf00d" * 5)) == 0
        _arm(ship, answers)
        assert ship.seat_row_debt(tmp_path, "main", prs) == (0, "2026-10-21", "open")
        answers[("git", "fetch", "origin", "feedface" * 5)] = (1, "", "could not read from remote")
        _arm(ship, answers)
        assert ship.seat_row_debt(tmp_path, "main", prs) is None

    def test_an_older_loader_without_the_count_reads_as_unread(self, ship, tmp_path, monkeypatch):
        """A sibling attribute read outside the guard raised AttributeError on a
        tree whose kept loader predates it (the first lane's failure-mode
        review). Dies to: the read outside the guard."""
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", self._LANES))
        real = ship._fragments_module()

        class Older:   # today's loader with one name withheld: the count's, read last (the mutants run found the gap)
            def __getattr__(self, name):
                if name == "lanes_since_row":
                    raise AttributeError(name)
                return getattr(real, name)

        monkeypatch.setattr(ship, "_FRAGMENTS", Older())
        spawns = _arm(ship, self._answers())
        assert ship.seat_row_debt(tmp_path, "main") is None
        assert spawns.count(self._PRUNED) == 1 and spawns.count(("gh", "pr", "list")) == 0

    def test_an_unreadable_records_ref_reads_as_unread(self, ship, tmp_path, monkeypatch):
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", self._LANES, pending_error="git for-each-ref failed"))
        _arm(ship, self._answers())
        assert ship.seat_row_debt(tmp_path, "main") is None

    def test_a_git_that_raises_or_a_channel_that_raises_reads_as_unread(self, ship, tmp_path, monkeypatch):
        """ship's runner raises Refused on a timeout or a missing git, and the
        tree read sat outside any guard, so the second lane's refusal would
        have fired on a git outage (code review). Dies to: the Refused or the
        channel's error reaching the caller."""
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", self._LANES))
        _arm(ship, self._answers())
        monkeypatch.setattr(ship, "_git", lambda *a, **k: (_ for _ in ()).throw(ship.Refused("git took longer than 10s")))
        assert ship.seat_row_debt(tmp_path, "main") is None
        monkeypatch.undo()
        channel = self._channel("win", self._LANES)
        channel.read_mail = lambda root, **kw: (_ for _ in ()).throw(RuntimeError("the fold raised"))
        monkeypatch.setattr(ship, "_MAIL", channel)
        _arm(ship, self._answers())
        assert ship.seat_row_debt(tmp_path, "main") is None

    def test_a_gh_that_answers_without_json_reads_as_unread_never_as_zero(self, ship, tmp_path, monkeypatch):
        """Dies to: the driver's Refused escaping the reader (open would refuse
        on a gh outage), or the empty answer counted as no lanes."""
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", self._LANES))
        _arm(ship, self._answers(gh_rc=1))
        assert ship.seat_row_debt(tmp_path, "main") is None

    def test_a_failed_tree_read_or_an_unnamed_box_reads_as_unread(self, ship, tmp_path, monkeypatch):
        monkeypatch.setattr(ship, "_MAIL", self._channel("win", self._LANES))
        _arm(ship, self._answers(tree_rc=128))
        assert ship.seat_row_debt(tmp_path, "main") is None
        monkeypatch.setattr(ship, "_MAIL", self._channel(None, self._LANES))
        spawns = _arm(ship, self._answers())
        assert ship.seat_row_debt(tmp_path, "main") is None
        assert spawns.count(("gh", "pr", "list")) == 0

    def test_a_tree_without_the_channel_reads_as_unread(self, ship, tmp_path, monkeypatch):
        monkeypatch.setattr(ship, "_mail_module", lambda: None)
        spawns = _arm(ship, self._answers())
        assert ship.seat_row_debt(tmp_path, "main") is None
        assert spawns.calls == []


class TestStaleBaseInStatus:
    """With the up-to-date rule off, `status` says when the base moved near
    the pull request's files since its CI ran (``_merge_rules.stale_base``,
    driven against real git in tests/test_stale_base.py); here, what the
    driver hands it and when it does not ask at all."""

    def test_the_rule_on_reads_no_stale_base(self, ship, tmp_path):
        """GitHub holds a stale lane itself under the rule: no run list, no fetch."""
        spawns = _arm(ship, _status_answers(tmp_path))
        assert ship.status() == 0
        assert spawns.count(("gh", "run", "list")) == 0 and spawns.count(("git", "fetch")) == 0

    def test_the_rule_off_names_a_move_near_the_files(self, ship, tmp_path, monkeypatch, capsys):
        answers = _status_answers(tmp_path, strict=False)
        runs = [{"workflowName": "CI", "createdAt": "2026-10-10T05:30:00Z", "headSha": HEAD, "conclusion": "success"}]
        answers.update({
            ("git", "fetch", "origin", "main", "lane/x"): (0, "", ""),
            ("gh", "run", "list", "--branch", "lane/x"): (0, json.dumps(runs), ""),
            ("git", "diff", "--name-only", "--no-renames", f"origin/main...{HEAD}"): (0, "tools/cc/ship.py\n", ""),
        })
        seen: dict = {}

        def judged(root, **kw):
            seen.update(kw)
            return {"tested": "1" * 40, "now": "2" * 40, "moved": 2, "near": ["tools/cc/ship.py (both changed)"],
                    "unread": ""}

        monkeypatch.setattr(ship._merge_rules, "stale_base", judged)
        _arm(ship, answers)
        assert ship.status() == 0
        out = capsys.readouterr().out
        assert "main moved 2 merge(s) since #7's CI tested it on 1111111, near its files" in out
        assert "python tools/cc/ship.py catch-up" in out
        assert seen["tested_when"] == "2026-10-10T05:30:00Z" and seen["pr_paths"] == ["tools/cc/ship.py"]
        assert seen["pr_rev"] == HEAD and seen["base_ref"] == "origin/main"


# ── the checkout's wiring note (DEF-1192) ─────────────────────────────────────

_NOTE_TELL = "loads none of the harness's hooks"


def _wired_checkout(ship, root: Path, *, drop: tuple[str, ...] = ()) -> None:
    """A checkout a session would launch in with the gates on: the blocking
    hooks on disk and the canonical wiring of every one but ``drop``
    (``tests/_wired_settings.py``, derived from the engine's table). Asserts
    first that the driver's own loader finds the reader, so a reader that
    stopped loading is a red here and never a silent pass."""
    assert ship._paths.hooks_module("_integrity") is not None, "hooks/_integrity.py is not beside tools/cc/ship.py"
    write_wired_settings(root, drop=drop)


class TestTheCheckoutWiringNote:
    """Every verb that pushes (`open`, `handoff`, `rebind`, `catch-up`) says, in
    one note per run, when a Claude Code session launched in the checkout it
    pushes from would run with the gates off (DEF-1192: a worktree checks out
    tracked files only, and the project settings file is gitignored). A note:
    the push goes ahead either way, and the reader is loaded by path, so a
    tools/cc subset without hooks/ stands down instead of dying on an import."""

    def test_open_notes_a_checkout_without_the_settings_file_and_still_opens(
            self, ship, tmp_path, forget_guard, capsys):
        _write_guard(tmp_path)
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        out = capsys.readouterr().out
        assert "note: .claude/settings.json in this checkout" in out and _NOTE_TELL in out
        assert spawns.count(("gh", "pr", "create")) == 1 and spawns.count(("git", "push")) == 1

    def test_open_is_silent_on_a_checkout_that_wires_every_deployed_gate(
            self, ship, tmp_path, forget_guard, capsys):
        _write_guard(tmp_path)
        _wired_checkout(ship, tmp_path)
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        assert "settings.json" not in capsys.readouterr().out
        assert spawns.count(("gh", "pr", "create")) == 1

    def test_open_names_the_gate_a_dropped_event_key_unwires(
            self, ship, tmp_path, forget_guard, capsys):
        """N7's shape: the hook file stays on disk, its event key is gone."""
        _write_guard(tmp_path)
        _wired_checkout(ship, tmp_path, drop=("stop_gate.py",))
        _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        out = capsys.readouterr().out
        assert "stop_gate.py" in out and "unwired" in out and "write_guard.py" not in out

    def test_the_note_stands_down_when_the_hooks_module_is_not_beside_the_tool(
            self, ship, tmp_path, forget_guard, capsys, monkeypatch):
        """A deploy that copied a subset of tools/cc, or an older hooks/ without
        the reader: the push still goes ahead, with no traceback and no note."""
        _write_guard(tmp_path)
        monkeypatch.setattr(ship._paths, "hooks_module", lambda name: None)
        spawns = _arm(ship, _open_answers(tmp_path))
        assert ship.open_pr() == 0
        assert "settings.json" not in capsys.readouterr().out
        assert spawns.count(("gh", "pr", "create")) == 1

    def test_handoff_that_opens_a_pull_request_notes_the_checkout_once(
            self, ship, tmp_path, forget_guard, capsys):
        """handoff returns through open_pr on this path, so the note is
        open_pr's, said once: not handoff's and then open_pr's again."""
        _toml(tmp_path, "handoff_push = true\n")
        _write_guard(tmp_path)
        answers = _open_answers(tmp_path)
        answers[("git", "status", "--porcelain", "-uno")] = (0, "", "")
        answers[_MEMORY_LOG] = (0, "abc1234\n", "")
        answers[_list_key()] = [(0, "[]", ""), (0, "[]", ""), _rows(_pr())]
        _arm(ship, answers)
        assert ship.handoff() == 0
        assert capsys.readouterr().out.count(_NOTE_TELL) == 1

    def test_handoff_onto_an_open_pull_request_notes_the_checkout_once(
            self, ship, tmp_path, capsys, monkeypatch):
        _toml(tmp_path, "handoff_push = true\n")
        spawns = _arm(ship, TestHandoffVerb._existing_pr_answers(tmp_path))
        monkeypatch.setattr(ship, "rebind", lambda dry_run=False: 0)
        assert ship.handoff() == 0
        assert spawns.count(("git", "push")) == 1
        assert capsys.readouterr().out.count(_NOTE_TELL) == 1

    def test_rebind_notes_the_checkout(self, ship, tmp_path, monkeypatch, capsys):
        """The operator's recorded practice runs catch-up and rebind from a
        hand-made scratch worktree of the lane: exactly the DEF-1192 shape, and
        a verb that said nothing beside one that spoke would read as a verdict."""
        _bind_clock(ship, monkeypatch)
        spawns = _arm(ship, _rebind_answers(tmp_path))
        assert ship.rebind() == 0
        assert capsys.readouterr().out.count(_NOTE_TELL) == 1
        assert spawns.count(("gh", "pr", "edit")) == 1

    def test_catch_up_notes_the_checkout_once_through_its_own_rebind(
            self, ship, tmp_path, monkeypatch, capsys):
        _bind_clock(ship, monkeypatch)
        spawns = _arm(ship, _catch_up_answers(tmp_path))
        assert ship.catch_up() == 0
        assert capsys.readouterr().out.count(_NOTE_TELL) == 1
        assert spawns.count(("git", "pull")) == 1
