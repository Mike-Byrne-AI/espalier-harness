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
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

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


@pytest.fixture
def ship():
    """A fresh copy of the script per row: each row replaces its runner."""
    return _load()


@pytest.fixture
def forget_guard():
    """Drop the guard the script loads by path, so one row's fixture guard is
    never the next row's answer."""
    yield
    sys.modules.pop("_ship_ci_guard", None)


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
        monkeypatch.setattr(ship, "subprocess", types.SimpleNamespace(
            run=fake_run, DEVNULL=subprocess.DEVNULL,
            TimeoutExpired=subprocess.TimeoutExpired))
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
                       merged="[]") -> dict:
    answers = _reads(root)
    answers.update({
        ("git", "fetch", "origin", "--quiet"): (0, "", ""),
        ("git", "status", "--porcelain", "-uno"): (0, dirty, ""),
        ("git", "status", "--porcelain", "--untracked-files=all"): (0, untracked, ""),
        ("git", "log", "--oneline"): (0, commits, ""),
        ("git", "merge-tree"): (0, "abc123\n", ""),   # the merge verdict: clean unless a test says otherwise
        ("git", "diff", "--name-only"): (0, "", ""),   # the attribute walk: nothing changed on both sides
        ("gh", "pr", "list", "--author"): (0, merged, ""),
    })
    return answers


def _memory(root: Path, *dates: str) -> None:
    rows = "".join(f"| {d} | a session row |\n" for d in dates)
    (root / "ESPALIER_MEMORY.md").write_text(
        "| Date | What |\n|---|---|\n" + rows, encoding="utf-8")


#: The read that asks whether this lane's own commits touch the memory file.
_MEMORY_LOG = ("git", "log", "--format=%h")


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
                  merge=(0, "", ""), armed='{"autoMergeRequest": {"enabledAt": "x"}}') -> dict:
    answers = _reads(root, branch=branch, base=base)
    answers.update({
        _list_key(branch): [(0, existing, ""), _rows(_pr())],
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
    def _existing_pr_answers(tmp_path, heads=(HEAD,)):
        answers = _reads(tmp_path)
        answers.update({
            _list_key(): [_rows(_pr(head=h)) for h in heads],
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
        _arm(ship, answers)
        order: list[str] = []
        monkeypatch.setattr(ship, "lane", lambda: order.append("lane") or 0)
        monkeypatch.setattr(ship, "open_pr", lambda **kw: order.append("open") or 0)
        assert ship.handoff() == 0
        assert order == ["lane", "open"]


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
        paths = sorted((ROOT / "espalier" / "assets" / "claude" / "commands").glob("*.md"))
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


# ── status ───────────────────────────────────────────────────────────────────

def _status_answers(root, *, branch="lane/x", open_rows=None, merged_rows="[]",
                    checks=None) -> dict:
    answers = _reads(root, branch=branch)
    answers.update({
        _list_key(branch, "open"): open_rows if open_rows is not None else _rows(_pr()),
        _list_key(branch, "merged"): (0, merged_rows, ""),
        ("gh", "pr", "checks"): checks or (0, json.dumps(
            [{"name": "lint", "bucket": "pass"}]), ""),
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
