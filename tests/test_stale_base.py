"""Contract tests for the stale-base read in ``tools/cc/_merge_rules.py``
(TP-479 Wave B-3, layer L3). With the up-to-date rule off, a pull request
merges on its own green CI, which tested it merged with the base as of its last
push. ``stale_base`` says when the base has moved since then NEAR the pull
request -- a path both changed, or a Python module one import away -- and stays
silent otherwise, so it never becomes the up-to-date rule by another name.

Git is the oracle for what moved and when: each case builds a throwaway repo
whose commits carry fixed committer dates, and the CI run's time is a string
between them, as ``gh run list`` answers it. The pure readers beside them
(``tested_at`` over recorded run payloads, the import-line parser) run without
git.
"""
# slow-exempt: one throwaway git repo per case, about a dozen git spawns each, measured 2026-10-10 at 7.1 s for the module on the Windows box
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_CC = REPO_ROOT / "tools" / "cc"


def _load():
    spec = importlib.util.spec_from_file_location("_merge_rules_under_test", TOOLS_CC / "_merge_rules.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rules():
    return _load()


@pytest.fixture
def mapper(monkeypatch):
    """tools/cc on the path, as the board and ship.py put it, so the symbol
    reading's import of ``_symbols`` resolves as it does for them."""
    monkeypatch.syspath_prepend(str(TOOLS_CC))


def _run(argv, *, cwd=None, timeout=30.0, input=None):
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout, input=input)
    return result.returncode, result.stdout, result.stderr


class _Repo:
    """A repository whose every commit carries the committer date it is given."""

    def __init__(self, root: Path):
        self.root = root
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.invalid")
        self.git("config", "user.name", "t")
        self.git("config", "core.autocrlf", "false")

    def git(self, *args: str, date: str | None = None) -> str:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        if date:
            env.update(GIT_COMMITTER_DATE=date, GIT_AUTHOR_DATE=date)
        result = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True,
                                encoding="utf-8", env=env, check=True)
        return result.stdout.strip()

    def commit(self, files: dict[str, str], date: str, message: str = "c") -> str:
        for rel, text in files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message, date=date)
        return self.git("rev-parse", "HEAD")


#: The base before the lane: a script that imports its sibling, the sibling,
#: an unrelated module, and a note.
_BASE_FILES = {
    "tools/a.py": "import sys\nimport b\n\nVALUE = b.VALUE\n",
    "tools/b.py": "VALUE = 1\n",
    "tools/c.py": "OTHER = 2\n",
    "notes.txt": "a note\n",
}
CI_RAN = "2026-10-10T05:30:00Z"


def _lane(repo: _Repo, main_change: dict[str, str] | None) -> tuple[str, str]:
    """Base at 05:00; the lane changes tools/a.py; CI ran at 05:30; main then
    moves at 06:00 with ``main_change`` (none: main never moved). Returns the
    lane's head and main's head."""
    repo.commit(_BASE_FILES, "2026-10-10T05:00:00Z", "base")
    repo.git("switch", "-q", "-c", "lane")
    head = repo.commit({"tools/a.py": _BASE_FILES["tools/a.py"] + "EXTRA = 3\n"}, "2026-10-10T05:10:00Z", "lane")
    repo.git("switch", "-q", "main")
    if main_change:
        repo.commit(main_change, "2026-10-10T06:00:00Z", "main moves")
    return head, repo.git("rev-parse", "HEAD")


def _judge(rules, repo: _Repo, head: str, tested_when: str = CI_RAN) -> dict:
    return rules.stale_base(repo.root, base_ref="main", tested_when=tested_when,
                            pr_paths=["tools/a.py"], pr_rev=head, run_=_run)


class TestStaleBase:
    def test_a_base_that_did_not_move_since_the_ci_is_silent(self, rules, tmp_path):
        repo = _Repo(tmp_path)
        head, now = _lane(repo, None)
        result = _judge(rules, repo, head)
        assert result["moved"] == 0 and result["near"] == [] and not result["unread"]
        assert result["tested"] == result["now"] == now
        assert rules.stale_line(result, "main", 7) == ""

    def test_a_path_both_changed_is_near(self, rules, tmp_path, mapper):
        repo = _Repo(tmp_path)
        head, _ = _lane(repo, {"tools/a.py": _BASE_FILES["tools/a.py"] + "MAIN = 4\n"})
        result = _judge(rules, repo, head)
        assert result["moved"] == 1
        # Both appended at the end, after VALUE's line: git conflicts there, and the clause says so.
        assert result["near"] == ["tools/a.py (both changed, meeting at the end of the file, VALUE)"]
        line = rules.stale_line(result, "main", 7)
        assert "main moved 1 merge(s) since #7's CI" in line and "tools/a.py (both changed" in line
        assert "python tools/cc/ship.py catch-up" in line and line.isascii()

    def test_a_module_the_lane_imports_changed_on_the_base_is_near(self, rules, tmp_path):
        """The import hop: main changed tools/b.py, which the lane's tools/a.py
        imports by its sibling name. Dies to: comparing paths only (the pack's
        named mutation)."""
        repo = _Repo(tmp_path)
        head, _ = _lane(repo, {"tools/b.py": "VALUE = 99\n"})
        result = _judge(rules, repo, head)
        assert result["near"] == ["tools/a.py imports tools/b.py (changed on main)"]

    def test_a_base_module_that_imports_the_lanes_file_is_near(self, rules, tmp_path):
        """The other direction: main added a module that imports the lane's
        file, from the root by its dotted name."""
        repo = _Repo(tmp_path)
        head, _ = _lane(repo, {"tools/d.py": "from tools import a\n", "tools/__init__.py": ""})
        result = _judge(rules, repo, head)
        assert "tools/d.py (changed on main) imports tools/a.py" in result["near"]

    def test_a_move_away_from_the_lanes_files_is_silent(self, rules, tmp_path):
        """Main moved, but only in a file the lane neither changes nor imports:
        the merge-tested green stands, so nothing is said. Dies to: firing on
        any move (the up-to-date rule by another name)."""
        repo = _Repo(tmp_path)
        head, _ = _lane(repo, {"tools/c.py": "OTHER = 5\n", "notes.txt": "another note\n"})
        result = _judge(rules, repo, head)
        assert result["moved"] == 1 and result["near"] == [] and not result["unread"]
        assert rules.stale_line(result, "main", 7) == ""

    def test_a_ci_run_older_than_every_base_commit_is_said_not_read(self, rules, tmp_path):
        repo = _Repo(tmp_path)
        head, _ = _lane(repo, {"tools/b.py": "VALUE = 99\n"})
        result = _judge(rules, repo, head, tested_when="2026-10-10T04:00:00Z")
        assert result["near"] == [] and "older than the CI run" in result["unread"]
        assert "stale-base check not read for #7's CI" in rules.stale_line(result, "main", 7)

    def test_a_base_that_is_not_here_is_said_not_read(self, rules, tmp_path):
        repo = _Repo(tmp_path)
        head, _ = _lane(repo, None)
        result = rules.stale_base(repo.root, base_ref="origin/main", tested_when=CI_RAN,
                                  pr_paths=["tools/a.py"], pr_rev=head, run_=_run)
        assert "origin/main is not here" in result["unread"]

    def test_no_run_yet_is_said_not_read(self, rules, tmp_path):
        repo = _Repo(tmp_path)
        head, _ = _lane(repo, {"tools/a.py": "changed\n"})
        result = _judge(rules, repo, head, tested_when="")
        assert result["near"] == [] and "tested anything yet" in result["unread"]


#: A module of two functions, for the symbol clauses (TP-702 Wave 2, 2-B).
_FUNCS = "import sys\n\n\ndef f():\n    return 1\n\n\ndef g():\n    return 2\n"


def _function_lane(repo: _Repo, lane_text: str, main_text: str) -> str:
    """Base at 05:00 holds tools/a.py as ``_FUNCS``; the lane writes
    ``lane_text`` there, CI ran at 05:30, then main writes ``main_text``."""
    repo.commit({**_BASE_FILES, "tools/a.py": _FUNCS}, "2026-10-10T05:00:00Z", "base")
    repo.git("switch", "-q", "-c", "lane")
    head = repo.commit({"tools/a.py": lane_text}, "2026-10-10T05:10:00Z", "lane")
    repo.git("switch", "-q", "main")
    repo.commit({"tools/a.py": main_text}, "2026-10-10T06:00:00Z", "main moves")
    return head


class TestTheSymbolClause:
    """Where a path both changed is Python and the head is here, the entry
    says what the catch-up will meet: the same function, different ones, or
    lines no node holds. The verdict itself is unchanged."""

    def test_the_same_function_is_named(self, rules, tmp_path, mapper):
        """Dies to: the meeting read from one side alone."""
        repo = _Repo(tmp_path)
        head = _function_lane(repo, _FUNCS.replace("return 1", "return 10"), _FUNCS.replace("return 1", "return 11"))
        assert _judge(rules, repo, head)["near"] == ["tools/a.py (both changed, meeting at f)"]

    def test_different_functions_are_said(self, rules, tmp_path, mapper):
        """Dies to: the certificate inverted (two functions read as one)."""
        repo = _Repo(tmp_path)
        head = _function_lane(repo, _FUNCS.replace("return 1", "return 10"), _FUNCS.replace("return 2", "return 20"))
        assert _judge(rules, repo, head)["near"] == [
            "tools/a.py (both changed, different functions, none shared or next to the other's)"]

    def test_a_symbol_read_that_fails_keeps_the_advisory(self, rules, tmp_path, mapper):
        """Dies to: the clause's failure raised out of stale_base (the advisory
        it decorates, which read fine, would be lost to a timed-out blob read)."""
        repo = _Repo(tmp_path)
        head = _function_lane(repo, _FUNCS.replace("return 1", "return 10"), _FUNCS.replace("return 2", "return 20"))

        def slow_blobs(argv, **kw):
            if argv[1:3] == ["cat-file", "blob"]:
                raise rules_timeout("git cat-file took longer than 30s")
            return _run(argv, **kw)

        class rules_timeout(Exception):
            pass

        result = rules.stale_base(repo.root, base_ref="main", tested_when=CI_RAN, pr_paths=["tools/a.py"],
                                  pr_rev=head, run_=slow_blobs)
        assert result["near"] == ["tools/a.py (both changed; symbols not read: rules_timeout)"], result
        assert "main moved 1 merge(s)" in rules.stale_line(result, "main", 7)

    def test_a_line_no_node_holds_is_unplaced(self, rules, tmp_path, mapper):
        """Dies to: an unplaced side certified (main's new import is at the
        top of the module, in no function)."""
        repo = _Repo(tmp_path)
        head = _function_lane(repo, _FUNCS.replace("return 1", "return 10"),
                              _FUNCS.replace("import sys\n", "import sys\nimport os\n"))
        assert _judge(rules, repo, head)["near"] == ["tools/a.py (both changed, unplaced lines)"]

    def test_a_head_not_here_is_never_given_a_function_verdict(self, rules, tmp_path, mapper):
        """Dies to: the fallback to the base printing a verdict (the base
        compared with itself is no comparison)."""
        repo = _Repo(tmp_path)
        _function_lane(repo, _FUNCS.replace("return 1", "return 10"), _FUNCS.replace("return 2", "return 20"))
        result = rules.stale_base(repo.root, base_ref="main", tested_when=CI_RAN, pr_paths=["tools/a.py"],
                                  pr_rev="main", run_=_run)
        assert result["near"] == ["tools/a.py (both changed; symbols not read: head not here)"]

    def test_a_mapper_that_cannot_be_imported_is_said(self, rules, tmp_path, monkeypatch):
        """Dies to: an import failure read as no reading (the clause would fall
        back to the bare path silently)."""
        monkeypatch.setitem(sys.modules, "_symbols", None)
        repo = _Repo(tmp_path)
        head = _function_lane(repo, _FUNCS.replace("return 1", "return 10"), _FUNCS.replace("return 2", "return 20"))
        (entry,) = _judge(rules, repo, head)["near"]
        assert entry.startswith("tools/a.py (both changed; symbols not read: the symbol mapper"), entry

    def test_a_path_that_is_not_python_keeps_its_bare_clause(self, rules, tmp_path, mapper):
        repo = _Repo(tmp_path)
        repo.commit(_BASE_FILES, "2026-10-10T05:00:00Z", "base")
        repo.git("switch", "-q", "-c", "lane")
        head = repo.commit({"notes.txt": "the lane's note\n"}, "2026-10-10T05:10:00Z", "lane")
        repo.git("switch", "-q", "main")
        repo.commit({"notes.txt": "main's note\n"}, "2026-10-10T06:00:00Z", "main moves")
        result = rules.stale_base(repo.root, base_ref="main", tested_when=CI_RAN, pr_paths=["notes.txt"],
                                  pr_rev=head, run_=_run)
        assert result["near"] == ["notes.txt (both changed)"]


class TestTestedAt:
    """When GitHub fixed the base a head's CI tested, from `gh run list`."""

    HEAD = "a" * 40

    def _r(self, name, at, conclusion="success", head=None):
        return {"workflowName": name, "createdAt": at, "conclusion": conclusion, "headSha": head or self.HEAD}

    def test_the_stalest_workflow_decides(self, rules):
        """A title edit re-runs only the guard on the same head; the test
        cells still carry the push's base. Dies to: the newest run overall."""
        runs = [self._r("Harness Guard", "2026-10-10T06:00:00Z"), self._r("CI", "2026-10-10T05:00:00Z"),
                self._r("Harness Guard", "2026-10-10T05:00:00Z")]
        assert rules.tested_at(runs, self.HEAD) == "2026-10-10T05:00:00Z"

    def test_a_workflows_newest_run_counts_not_its_first(self, rules):
        runs = [self._r("CI", "2026-10-10T05:00:00Z"), self._r("CI", "2026-10-10T07:00:00Z")]
        assert rules.tested_at(runs, self.HEAD) == "2026-10-10T07:00:00Z"

    def test_a_cancelled_or_skipped_run_tested_nothing(self, rules):
        runs = [self._r("CI", "2026-10-10T05:00:00Z"), self._r("Guard", "2026-10-10T04:00:00Z", "cancelled"),
                self._r("Bench", "2026-10-10T03:00:00Z", "skipped")]
        assert rules.tested_at(runs, self.HEAD) == "2026-10-10T05:00:00Z"

    def test_another_heads_runs_do_not_count(self, rules):
        runs = [self._r("CI", "2026-10-10T05:00:00Z", head="b" * 40)]
        assert rules.tested_at(runs, self.HEAD) == ""
        assert rules.tested_at("not a list", self.HEAD) == ""


class TestImportNames:
    @pytest.mark.parametrize("line, expected", [
        ("import b", (0, ["b"])),
        ("    import a.b as c, d", (0, ["a.b", "d"])),
        ("from tools import a", (0, ["tools", "tools.a"])),
        ("from . import x, y as z", (1, ["x", "y"])),
        ("from ..pkg.mod import (thing,", (2, ["pkg.mod", "pkg.mod.thing"])),
        ("from x import *", (0, ["x"])),
        ("important = 1", (0, [])),
    ])
    def test_each_import_shape(self, rules, line, expected):
        assert rules._import_names(line) == expected


class TestALaneCarriesItsRowAsASessionLogFile:
    """The ship driver's row question, read by real git: since 2026-10-10 a
    handoff writes its row as a file under memory/session-log.d/, so a lane
    whose only commit adds one carries its row. Mutation seen red: the memory
    file read alone (``ship.lane_carries_memory_row`` before the review of the
    Wave C batch), which refused every such handoff on a tree that pushes at
    the handoff."""

    @staticmethod
    def _ship(monkeypatch):
        monkeypatch.syspath_prepend(str(TOOLS_CC))
        spec = importlib.util.spec_from_file_location("_ship_for_the_row", TOOLS_CC / "ship.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod

    @pytest.mark.parametrize("added, carries", [
        ({"memory/session-log.d/2026-10-11-120000-win.md": "| 2026-10-11 | a row | n |\n"}, True),
        ({"docs/notes.md": "a note\n"}, False),
        ({"ESPALIER_MEMORY.md": "# m\n\nedited\n"}, True),
    ])
    def test_the_row_is_a_memory_file_change_or_an_added_session_log_file(
            self, tmp_path, monkeypatch, added, carries):
        ship = self._ship(monkeypatch)
        repo = _Repo(tmp_path)
        repo.commit({"ESPALIER_MEMORY.md": "# m\n", "memory/session-log.d/2026-10-10-120000-air.md":
                     "| 2026-10-10 | an older row | n |\n"}, "2026-10-10T12:00:00+00:00", "base")
        repo.git("update-ref", "refs/remotes/origin/main", "main")
        repo.git("switch", "-q", "-c", "lane/x")
        repo.commit(added, "2026-10-11T12:00:00+00:00", "the lane")
        assert ship.lane_carries_memory_row("main", tmp_path) is carries
