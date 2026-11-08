"""Contract tests that pin the board's two reads of the base branch's tree
(``tools/cc/board.py``) to its tip, so a checkout that stops moving reads what
the base holds while every other board line reads GitHub or the base live.

The ledger line counts the live rows there, through the base tree's own
generator and fragment loader (DEF-3006). Without this the line drifts
silently: seen 2026-10-14, a checkout on a merged branch read 274 all day
while main held 279. The checks line's base-run roster lists the base's
workflow files (DEF-5084): a push workflow merged to main mid-window is read
at the next board read, not at the reading seat's next catch-up.

Real git is the oracle for what a ref holds, so each case builds a scratch
repository whose checkout sits behind ``origin/main``; GitHub and the mail
channel are stubbed as in ``tests/test_board.py``.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_board import _GREEN_RUNS, _gh, _run, _stub_channel
from tests.test_generate_ledger_regions import _ledger
from tests.test_ledger_fragments import _row_file
from tests._live_tree import copy_checkout

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_CC = REPO_ROOT / "tools" / "cc"

#: Appended to the base's generator in the sentinel case: a count no tree holds,
#: so only the base tree's own generator can print it.
_SENTINEL_GENERATOR = "\n\ndef live_member_ids(text):\n    return {f'X-{i}' for i in range(41)}\n"


def _load(name: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, TOOLS_CC / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def board():
    return _load("board", "board_ledger_base_under_test")


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8",
                          timeout=30, check=True)
    return done.stdout.strip()


def _behind_its_base(tmp_path: Path, *, base_generator_tail: str = "", base_loader_tail: str = "",
                     base_attributes: str = "", base_drops_ledger: bool = False) -> tuple[Path, str]:
    """A checkout on a branch one commit behind ``origin/main``. Both commits
    carry this checkout's ``tools/cc`` and the fixture ledger; the first holds
    one row file (three live rows with the fixture's two), the second adds
    another (four) and, as asked, appends to the base's own generator or
    fragment loader, writes the base's ``.gitattributes``, or deletes the
    base's ledger. The remote-tracking ref names the second commit."""
    root = tmp_path / "work"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    for key, value in (("user.email", "t@example.com"), ("user.name", "t"), ("core.autocrlf", "false")):
        _git(root, "config", key, value)
    copy_checkout(TOOLS_CC, root / "tools" / "cc", ignore=shutil.ignore_patterns("__pycache__"))
    rows = root / "task-packs" / "ledger.d"
    rows.mkdir(parents=True)
    (root / "task-packs" / "FORWARD_LEDGER.md").write_bytes(_ledger().encode("utf-8"))
    (rows / "DEF-8.md").write_bytes(_row_file("DEF-8").encode("utf-8"))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "one row file")
    _git(root, "branch", "lane")
    (rows / "DEF-9.md").write_bytes(_row_file("DEF-9").encode("utf-8"))
    for module, tail in (("generate_ledger_regions.py", base_generator_tail), ("_record_fragments.py", base_loader_tail)):
        if tail:
            path = root / "tools" / "cc" / module
            path.write_bytes(path.read_bytes() + tail.encode("utf-8"))
    if base_attributes:
        (root / ".gitattributes").write_bytes(base_attributes.encode("utf-8"))
    if base_drops_ledger:
        _git(root, "rm", "-q", "-r", "task-packs")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "a second row file")
    tip = _git(root, "rev-parse", "HEAD")
    _git(root, "update-ref", "refs/remotes/origin/main", tip)
    _git(root, "switch", "-q", "lane")
    return root, tip


def _stub(monkeypatch, board) -> None:
    """GitHub and the mail channel stubbed as in ``tests/test_board.py``, with
    the two reads under test left real: the base fetch and the ledger count."""
    real = (board.fetch_base, board.read_ledger_at_base)
    _stub_channel(monkeypatch, board)
    monkeypatch.setattr(board, "fetch_base", real[0])
    monkeypatch.setattr(board, "read_ledger_at_base", real[1])


def _runner(board, calls: list[list[str]]):
    """GitHub answered from fixtures; every other program (git, the child
    interpreter) runs for real through the board's own spawn."""

    def run(argv, **kw):
        calls.append(list(argv))
        if Path(argv[0]).name.lower().startswith("gh"):
            answers = {"pr list": [], "run list": _GREEN_RUNS}
            return 0, json.dumps(answers[" ".join(argv[1:3])]), ""
        return board.run(argv, **kw)

    return run


class TestTheLedgerLineReadsTheBase:
    def test_a_checkout_behind_its_base_reads_the_bases_count(self, board, monkeypatch, tmp_path):
        """Dies to: the count read from the working tree (the defect)."""
        root, tip = _behind_its_base(tmp_path)
        _stub(monkeypatch, board)
        assert board.read_ledger_live(root) == 3, "precondition: the working tree is one row behind"
        collected = board.collect(root, fetch=False, run_=_runner(board, []))
        assert collected["ledger_live"] == 4
        assert f"ledger:   4 live rows at origin/main ({tip[:7]})" in board.render(collected)

    def test_the_count_is_the_base_trees_own_generator(self, board, monkeypatch, tmp_path):
        """Dies to: the base's files counted through this checkout's generator,
        which a checkout on older code would misread."""
        root, _tip = _behind_its_base(tmp_path, base_generator_tail=_SENTINEL_GENERATOR)
        _stub(monkeypatch, board)
        assert board.collect(root, fetch=False, run_=_runner(board, []))["ledger_live"] == 41

    def test_a_missing_base_ref_reads_the_working_tree_and_says_so(self, board, monkeypatch, tmp_path):
        """Dies to: a silent fallback (a working-tree count printed as if it
        were the base's), or no count at all on a clone without the ref."""
        root, _tip = _behind_its_base(tmp_path)
        _git(root, "update-ref", "-d", "refs/remotes/origin/main")
        _stub(monkeypatch, board)
        collected = board.collect(root, fetch=False, run_=_runner(board, []))
        assert collected["ledger_live"] == 3
        line = next(ln for ln in board.render(collected).splitlines() if ln.startswith("ledger:"))
        assert line.startswith("ledger:   3 live rows in this working tree") and "origin/main" in line, line

    def test_the_base_is_fetched_once_per_read_and_not_under_no_fetch(self, board, monkeypatch, tmp_path):
        """Dies to: a count at a remote-tracking ref nothing refreshes (no pull
        request armed, so the stale section's fetch never runs), or a second
        fetch when it does."""
        root, _tip = _behind_its_base(tmp_path)
        _stub(monkeypatch, board)
        handed: list[bool] = []
        monkeypatch.setattr(board, "read_stale_section",
                            lambda root, base, prs, strict, **kw: handed.append(kw.get("fetch", True)))
        fetches = lambda calls: [c for c in calls if c[:4] == ["git", "fetch", "origin", "main"]]  # noqa: E731
        calls: list[list[str]] = []
        board.collect(root, fetch=True, run_=_runner(board, calls))
        assert len(fetches(calls)) == 1, calls
        assert handed == [False], "the stale section fetches the base a second time"
        calls.clear()
        board.collect(root, fetch=False, run_=_runner(board, calls))
        assert fetches(calls) == []

    def test_the_line_says_when_the_base_is_as_last_fetched(self, board, monkeypatch, tmp_path):
        """Dies to: a failed or skipped fetch printed as the base's tip, the
        defect again under a label that reads as live (failure-mode review)."""
        root, tip = _behind_its_base(tmp_path)
        _stub(monkeypatch, board)

        def ledger_line(fetch: bool) -> str:
            text = board.render(board.collect(root, fetch=fetch, run_=_runner(board, [])))
            return next(ln for ln in text.splitlines() if ln.startswith("ledger:"))

        assert ledger_line(True).startswith(f"ledger:   4 live rows at origin/main ({tip[:7]}), as last fetched "
                                            "(the fetch failed: "), "this scratch clone has no origin to fetch"
        assert ledger_line(False) == f"ledger:   4 live rows at origin/main ({tip[:7]}), as last fetched (--no-fetch)"
        _git(root, "remote", "add", "origin", str(root))
        assert ledger_line(True) == f"ledger:   4 live rows at origin/main ({tip[:7]})"

    def test_an_export_ignored_row_directory_reads_the_working_tree_and_says_so(self, board, monkeypatch,
                                                                                 tmp_path):
        """Dies to: git archive's export-ignore dropping the rows, so the base
        reads as its ledger file alone (two rows here, zero on the live tree)
        under a label that says it is the base's (failure-mode review)."""
        root, _tip = _behind_its_base(tmp_path, base_attributes="task-packs/ledger.d export-ignore\n")
        _stub(monkeypatch, board)
        collected = board.collect(root, fetch=False, run_=_runner(board, []))
        assert collected["ledger_live"] == 3
        line = next(ln for ln in board.render(collected).splitlines() if ln.startswith("ledger:"))
        assert line.startswith("ledger:   3 live rows in this working tree (git archive of origin/main leaves out "), line
        assert "export-ignore" in line, line

    def test_a_base_without_a_ledger_says_so(self, board, monkeypatch, tmp_path):
        """Dies to: the line vanishing when the base keeps no ledger (a tree
        before its first push of one, a fork)."""
        root, tip = _behind_its_base(tmp_path, base_drops_ledger=True)
        _stub(monkeypatch, board)
        text = board.render(board.collect(root, fetch=False, run_=_runner(board, [])))
        assert f"ledger:   no ledger at origin/main ({tip[:7]})" in text, text

    def test_a_base_whose_loader_moved_the_rows_is_refused_by_name(self, board, monkeypatch, tmp_path):
        """Dies to: a parked checkout cutting the archive by its own names and
        counting a base that moved its rows as the ledger file alone."""
        root, _tip = _behind_its_base(tmp_path, base_loader_tail="\nLEDGER_DIR = 'task-packs/rows.d'\n")
        _stub(monkeypatch, board)
        text = board.render(board.collect(root, fetch=False, run_=_runner(board, [])))
        line = next(ln for ln in text.splitlines() if ln.startswith("ledger:"))
        assert line.startswith("ledger:   unread (") and "task-packs/rows.d" in line and "catch this checkout up" in line, line

    def test_an_unreadable_archive_costs_only_the_ledger_line(self, board, monkeypatch, tmp_path):
        """Dies to: a tar error escaping ``collect`` and taking the whole board
        with it (both reviews)."""
        root, _tip = _behind_its_base(tmp_path)
        _stub(monkeypatch, board)

        def broken(*a, **k):
            raise board.tarfile.ReadError("planted: not a tar")

        monkeypatch.setattr(board.tarfile, "open", broken)
        text = board.render(board.collect(root, fetch=False, run_=_runner(board, [])))
        assert "ledger:   unread (the archive of origin/main could not be read: ReadError: planted" in text, text
        assert "open PRs:" in text


def _workflow(tail: str = "") -> bytes:
    return f"name: w\non:\n  push:\n    branches: [main]\n  workflow_dispatch:\n{tail}".encode("utf-8")


#: A concurrency whose cancel a newer push's run supersedes (one group per
#: workflow and ref), as release.yml's is.
_SUPERSEDING = "concurrency:\n  group: ${{ github.workflow }}-${{ github.ref }}\n  cancel-in-progress: true\n"


def _workflows_behind_their_base(tmp_path: Path) -> tuple[Path, str]:
    """A checkout on a branch one commit behind ``origin/main`` in its
    workflow files. Both commits hold the post-merge proof and a
    pull-request-only workflow; the first holds ``gone.yml``, which the second
    deletes; the second adds ``added.yml`` (a concurrency that supersedes),
    ``crlf.yml`` (a BOM and CRLF line ends, stored as written) and a folder
    named like a workflow. The checkout holds the first commit."""
    root = tmp_path / "work"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    for key, value in (("user.email", "t@example.com"), ("user.name", "t"), ("core.autocrlf", "false")):
        _git(root, "config", key, value)
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "post-merge.yml").write_bytes(_workflow())
    (workflows / "test.yml").write_bytes(b"on:\n  pull_request:\n    branches: [main]\n")
    (workflows / "gone.yml").write_bytes(_workflow())
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "the first workflows")
    _git(root, "branch", "lane")
    (workflows / "gone.yml").unlink()
    (workflows / "added.yml").write_bytes(_workflow(_SUPERSEDING))
    (workflows / "crlf.yml").write_bytes(b"\xef\xbb\xbf" + _workflow().replace(b"\n", b"\r\n"))
    (workflows / "folder.yml").mkdir()
    (workflows / "folder.yml" / "inner.yml").write_bytes(_workflow())
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "one added, one deleted")
    tip = _git(root, "rev-parse", "HEAD")
    _git(root, "update-ref", "refs/remotes/origin/main", tip)
    _git(root, "switch", "-q", "lane")
    return root, tip


def _gh_and_git(board, answers: dict):
    """GitHub answered by ``tests/test_board.py``'s fixture runner (its calls
    recorded on ``.calls``); git runs for real through the board's own spawn."""
    gh = _gh(answers)

    def run(argv, **kw):
        if Path(argv[0]).name.lower().startswith("gh"):
            return gh(argv, **kw)
        return board.run(argv, **kw)

    run.calls = gh.calls  # type: ignore[attr-defined]
    return run


def _workflow_reads(run) -> list[str]:
    return sorted(c[c.index("--workflow") + 1] for c in run.calls if c[1:3] == ["run", "list"] and "--workflow" in c)


class TestTheRosterReadsTheBase:
    """The base-run roster is the workflow files at ``origin/<base>``, the
    checkout's only where the clone cannot list them, and the line says so."""

    _RED = [dict(_run("completed", "failure", "d" * 40), databaseId=9)]
    _NOTE = "          (push workflows listed from this working tree: "

    def test_a_workflow_added_on_the_base_is_read_before_the_checkout_holds_it(self, board, monkeypatch, tmp_path):
        """Dies to: the roster listed from the working tree, which a checkout
        behind its base reads without the new workflow, so its red shows on
        no line until the reading seat catches up (the defect)."""
        root, _tip = _workflows_behind_their_base(tmp_path)
        assert not (root / ".github" / "workflows" / "added.yml").exists(), "precondition: the checkout is behind"
        _stub_channel(monkeypatch, board)
        run = _gh_and_git(board, {"pr list": [], "run list": _GREEN_RUNS, "run list added.yml": self._RED})
        text = board.render(board.collect(root, fetch=False, run_=run))
        assert "checks:   added (main, advisory): red since ddddddd (run 9) (no green among the runs read)" in text, text
        assert self._NOTE not in text, text
        # Read at the ref as last fetched, which this checks line says itself.
        assert "          (push workflows listed at origin/main, as last fetched (--no-fetch))" in text, text

    def test_the_roster_is_read_after_the_base_fetch(self, board, monkeypatch, tmp_path):
        """Dies to: the roster read before ``collect`` fetches the base, so a
        workflow merged since the last fetch waits a whole board read more
        (every other row reads an ``update-ref``'d ref with ``fetch=False``;
        the failure-mode review's mutant moved the fetch below the checks
        section and 216 board tests stayed green)."""
        origin, tip = _workflows_behind_their_base(tmp_path)
        clone = tmp_path / "clone"
        _git(tmp_path, "clone", "-q", "--no-hardlinks", str(origin), str(clone))
        # The clone checks out the origin's lane (its first commit); its
        # origin/main is put back there, a base as last fetched before the merge.
        _git(clone, "update-ref", "refs/remotes/origin/main", _git(clone, "rev-parse", "HEAD"))
        assert "added.yml" not in board.base_run_workflows(clone, "main", run_=board.run)[0], "precondition"
        _stub(monkeypatch, board)
        run = _gh_and_git(board, {"pr list": [], "run list": _GREEN_RUNS, "run list added.yml": self._RED})
        text = board.render(board.collect(clone, fetch=True, run_=run))
        assert "added.yml" in _workflow_reads(run), _workflow_reads(run)
        assert "checks:   added (main, advisory): red since ddddddd (run 9)" in text, text
        assert _git(clone, "rev-parse", "refs/remotes/origin/main") == tip

    def test_a_workflow_deleted_on_the_base_is_not_read_while_the_checkout_keeps_it(self, board, monkeypatch,
                                                                                    tmp_path):
        """Dies to: a workflow the base no longer holds read from the working
        tree (a checkout behind the deletion reads a ghost, and a lane that
        deletes one stops reading it on its own board), or a pull-request
        workflow, a folder or the post-merge proof read onto the roster."""
        root, _tip = _workflows_behind_their_base(tmp_path)
        assert (root / ".github" / "workflows" / "gone.yml").is_file(), "precondition: the checkout keeps it"
        _stub_channel(monkeypatch, board)
        run = _gh_and_git(board, {"pr list": [], "run list": _GREEN_RUNS, "run list gone.yml": self._RED})
        text = board.render(board.collect(root, fetch=False, run_=run))
        assert "gone" not in text, text
        assert _workflow_reads(run) == ["added.yml", "crlf.yml", "post-merge.yml"], _workflow_reads(run)

    def test_the_bases_files_are_decoded_as_the_checkouts_are(self, board, tmp_path):
        """Dies to: a BOM or CRLF line ends at the base hiding a push trigger
        the checkout's read sees, a superseding concurrency lost, or the
        post-merge proof or a folder read (a spawn for each)."""
        root, _tip = _workflows_behind_their_base(tmp_path)
        calls: list[list[str]] = []

        def run(argv, **kw):
            calls.append(list(argv))
            return board.run(argv, **kw)

        assert board.base_run_workflows(root, "main", run_=run) == ({"added.yml": True, "crlf.yml": False}, "")
        # added, crlf and the pull-request workflow, whose text alone says it is one.
        assert len([c for c in calls if c[1:3] == ["cat-file", "blob"]]) == 3, calls

    def test_a_missing_base_ref_reads_the_checkout_and_the_line_says_so(self, board, monkeypatch, tmp_path):
        """Dies to: a silent fallback (the working tree's roster printed as if
        it were the base's), or no roster at all on a clone without the ref."""
        root, _tip = _workflows_behind_their_base(tmp_path)
        _git(root, "update-ref", "-d", "refs/remotes/origin/main")
        _stub_channel(monkeypatch, board)
        run = _gh_and_git(board, {"pr list": [], "run list": _GREEN_RUNS, "run list gone.yml": self._RED})
        text = board.render(board.collect(root, fetch=False, run_=run))
        assert "checks:   gone (main, advisory): red since ddddddd (run 9)" in text, text
        assert self._NOTE + "origin/main is not in this clone)" in text, text

    def test_a_listing_git_does_not_give_reads_the_checkout_and_says_why(self, board, tmp_path):
        """Dies to: a failed or killed listing read as an empty roster, every
        base-run line gone silent under a label that reads as the base's."""
        root, _tip = _workflows_behind_their_base(tmp_path)

        def listing(answer):
            def run(argv, **kw):
                if argv[1] == "ls-tree":
                    if isinstance(answer, Exception):
                        raise answer
                    return answer
                return board.run(argv, **kw)
            return run

        roster, why = board.base_run_workflows(root, "main", run_=listing(board.Unresolvable("git ls-tree took longer than 15s")))
        assert roster == {"gone.yml": False}
        assert "origin/main" in why and "git ls-tree took longer than 15s" in why, why
        roster, why = board.base_run_workflows(root, "main", run_=listing((128, "", "fatal: not a tree object")))
        assert roster == {"gone.yml": False}
        assert "origin/main" in why and "fatal: not a tree object" in why, why

    def test_a_fallback_over_an_empty_roster_is_still_said(self, board, monkeypatch, tmp_path):
        """Dies to: the note kept off when the checkout holds no push
        workflow, so a failed listing prints "none red" over a base whose push
        workflows went unread (both reviews: the case DEF-5084 names, silent)."""
        root, _tip = _workflows_behind_their_base(tmp_path)
        (root / ".github" / "workflows" / "gone.yml").unlink()
        _stub_channel(monkeypatch, board)
        gh = _gh_and_git(board, {"pr list": [], "run list": _GREEN_RUNS})

        def run(argv, **kw):
            if argv[:2] == ["git", "ls-tree"]:
                return 128, "", "fatal: not a tree object"
            return gh(argv, **kw)

        collected = board.collect(root, fetch=False, run_=run)
        assert collected["post_merge_checks"]["base_runs"] == {}
        text = board.render(collected)
        assert self._NOTE + "git ls-tree on origin/main failed (fatal: not a tree object))" in text, text

    def test_a_file_git_does_not_give_stays_on_the_roster(self, board, tmp_path):
        """Dies to: a workflow whose text git did not hand over (a killed or
        failed read) dropped from the roster instead of read by its gh read,
        as an unreadable file in the checkout is."""
        root, _tip = _workflows_behind_their_base(tmp_path)
        answers = iter([board.Unresolvable("git cat-file took longer than 15s"), (128, "", "fatal: bad object")])

        def run(argv, **kw):
            if argv[1] == "cat-file":
                answer = next(answers, None)
                if isinstance(answer, Exception):
                    raise answer
                if answer is not None:
                    return answer
            return board.run(argv, **kw)

        assert board.base_run_workflows(root, "main", run_=run) == ({"added.yml": False, "crlf.yml": False}, "")

    def test_a_spent_budget_starts_no_git_read_and_says_so(self, board, tmp_path):
        """Dies to: the roster's git reads started past the base-run budget
        the gh reads share, or the fallback taken in silence."""
        root, _tip = _workflows_behind_their_base(tmp_path)
        calls: list[list[str]] = []
        roster, why = board.base_run_workflows(root, "main", run_=lambda argv, **kw: calls.append(argv),
                                               deadline=10.0, clock=lambda: 10.0)
        assert calls == [] and roster == {"gone.yml": False}
        assert "no time was left" in why and "origin/main" in why, why


class TestTheChildsContract:
    @pytest.mark.contract
    def test_the_names_the_child_calls_are_this_trees_ledger_tools(self, board):
        """The child calls the base's generator and loader by name, and the
        archive is cut by this checkout's names for the ledger and its rows: a
        rename lands by expand, then contract (root CLAUDE.md Core Rule 15), or
        every parked checkout reads the line as unread until it moves."""
        gen = _load("generate_ledger_regions", "gen_for_board_child_contract")
        rf = gen.record_fragments()
        for name in ("record_fragments", "live_member_ids"):
            assert callable(getattr(gen, name, None)), name
        assert callable(getattr(rf, "ledger_view_from_texts", None))
        for name in ("record_fragments", "ledger_view_from_texts", "live_member_ids", "LEDGER_FILE", "LEDGER_DIR"):
            assert name in board._BASE_COUNT, name
        assert (board.LEDGER, board.LEDGER_DIR) == (rf.LEDGER_FILE, rf.LEDGER_DIR)
