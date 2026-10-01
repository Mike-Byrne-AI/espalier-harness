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
    }


def _pr(number: int = 7, title: str = "feat: a thing", state: str = "OPEN",
        head: str = HEAD, merge_state: str = "CLEAN", armed: bool = True,
        merge_oid: str | None = None) -> dict:
    return {
        "number": number,
        "title": title,
        "url": f"https://example.invalid/pull/{number}",
        "state": state,
        "headRefOid": head,
        "mergeStateStatus": merge_state,
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
        ("gh", "pr", "list", "--author"): (0, merged, ""),
    })
    return answers


def _memory(root: Path, *dates: str) -> None:
    rows = "".join(f"| {d} | a session row |\n" for d in dates)
    (root / "ESPALIER_MEMORY.md").write_text(
        "| Date | What |\n|---|---|\n" + rows, encoding="utf-8")


class TestPreflight:
    def test_the_handoff_notice_names_a_memory_row_older_than_today(
            self, ship, tmp_path, capsys):
        _memory(tmp_path, "2026-09-28", "2026-09-29")
        _arm(ship, _preflight_answers(tmp_path))
        assert ship.preflight(today="2026-09-30") == 0
        out = capsys.readouterr().out
        assert "2026-09-29" in out
        assert "the handoff has not run this session" in out

    def test_no_handoff_notice_when_the_newest_memory_row_is_todays(
            self, ship, tmp_path, capsys):
        _memory(tmp_path, "2026-09-28", "2026-09-30")
        _arm(ship, _preflight_answers(tmp_path))
        assert ship.preflight(today="2026-09-30") == 0
        assert "the handoff has not run" not in capsys.readouterr().out

    def test_untracked_files_are_noted_and_do_not_stop_the_ship(
            self, ship, tmp_path, capsys):
        _memory(tmp_path, "2026-09-30")
        spawns = _arm(ship, _preflight_answers(
            tmp_path, untracked="?? scratch.txt\n?? notes.md\n M tracked.py\n"))
        assert ship.preflight(today="2026-09-30") == 0
        out = capsys.readouterr().out
        assert "2 untracked file(s) will not ship" in out
        assert "scratch.txt" in out
        assert spawns.mutations == []

    def test_a_dirty_tracked_tree_is_refused_before_anything_mutates(
            self, ship, tmp_path):
        spawns = _arm(ship, _preflight_answers(tmp_path, dirty=" M CLAUDE.md\n"))
        with pytest.raises(ship.Refused) as stop:
            ship.preflight(today="2026-09-30")
        assert "the tracked tree is dirty" in str(stop.value)
        assert spawns.mutations == []

    def test_an_empty_commit_range_is_refused(self, ship, tmp_path):
        spawns = _arm(ship, _preflight_answers(tmp_path, commits="\n"))
        with pytest.raises(ship.Refused) as stop:
            ship.preflight(today="2026-09-30")
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
        assert ship.preflight(today="2026-09-30") == 0
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
        assert ship.preflight(today="2026-09-30") == 0
        assert "red after merge" not in capsys.readouterr().out

    def test_a_tree_that_is_not_a_git_checkout_is_refused(self, ship, tmp_path):
        answers = _preflight_answers(tmp_path)
        answers[("git", "rev-parse", "--show-toplevel")] = (128, "", "not a repository")
        spawns = _arm(ship, answers)
        with pytest.raises(ship.Refused) as stop:
            ship.preflight(today="2026-09-30")
        assert "not inside a git checkout" in str(stop.value)
        assert spawns.mutations == []

    def test_a_default_branch_gh_cannot_name_is_refused(self, ship, tmp_path):
        answers = _preflight_answers(tmp_path)
        answers[("gh", "repo", "view")] = (1, "", "gh: not logged in")
        spawns = _arm(ship, answers)
        with pytest.raises(ship.Refused) as stop:
            ship.preflight(today="2026-09-30")
        assert "gh could not name the default branch" in str(stop.value)
        assert "not logged in" in str(stop.value)
        assert spawns.mutations == []

    def test_a_gh_read_that_answers_without_json_is_refused(self, ship, tmp_path):
        _memory(tmp_path, "2026-09-30")
        spawns = _arm(ship, _preflight_answers(tmp_path, merged="<html>a login page</html>"))
        with pytest.raises(ship.Refused) as stop:
            ship.preflight(today="2026-09-30")
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
        assert ship.newest_memory_row_date(tmp_path) is None
        problem = ship.memory_problem(tmp_path)
        assert problem.startswith("ESPALIER_MEMORY.md: ") and "not UTF-8 text" in problem

    def test_a_utf16_memory_file_with_a_mark_still_answers(self, ship, tmp_path):
        (tmp_path / "ESPALIER_MEMORY.md").write_bytes(
            "| 2026-10-01 | a row |\n".encode("utf-16"))
        assert ship.newest_memory_row_date(tmp_path) == "2026-10-01"
        assert ship.memory_problem(tmp_path) == ""

    def test_an_absent_memory_file_is_no_problem(self, ship, tmp_path):
        assert ship.newest_memory_row_date(tmp_path) is None
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
