"""Contract tests for ``tools/cc/seat.py``: launch, list and retire a clone's
seats (TP-701 Wave B, B-2).

REAL-GIT cases, because what a seat holds is git's answer: a bare origin, a
clone named ``box`` (``git config espalier.machine``), and worktrees under its
``.claude/worktrees/`` created, named and removed by the driver; claims go out
on the scratch origin's mail refs through ``mail.py``'s own send. The session
registry is a temp config dir (``checkout_sync.claude_config_dirs`` patched),
so a "live session" is this process's pid and a gone one is a reaped child's.
``claude`` never runs: the one spawn, ``subprocess.call``, is replaced.

The pack's reds: ``launch`` with a registry entry whose cwd is the target and
whose pid is this process refuses, and with a dead pid proceeds to the print;
``retire`` on a scratch channel closes the seat's claim so ``claims`` no
longer lists it. Its named mutation, the cwd comparison dropped from the
liveness oracle, makes ``launch`` proceed into an occupied checkout.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests._git_oracle import _git_env

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE = REPO_ROOT / "tools" / "cc" / "seat.py"


def _load(alias: str):
    """The importlib dance ``tests/CLAUDE.md`` mandates for a ``tools/cc`` module."""
    spec = importlib.util.spec_from_file_location(alias, MODULE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def seat():
    # Bound by name through the loader so the derived-population census can
    # read this file (its loader-function rule); a dance inlined in the fixture
    # binds only ``spec``/``mod``, which the census reads as unresolved.
    driver = _load("seat_under_test")
    return driver


@pytest.fixture(autouse=True)
def _outside_a_session(monkeypatch):
    """The suite may run inside a Claude session; the oracle then insists the
    registry list it, and finds the caller by the ids a session exports.
    These cases are about the seat, not the caller."""
    for name in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_CODE_SESSION_ID"):
        monkeypatch.delenv(name, raising=False)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=_git_env(), check=check, timeout=45)


def _out(repo: Path, *args: str) -> str:
    return _git(repo, *args).stdout.strip()


def _dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=30)
    return child.pid


@pytest.fixture
def clone(tmp_path):
    """A bare origin with one commit and a clone of it named ``box``, with
    per-worktree config on (as SessionStart leaves a named clone)."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "--quiet", "-b", "main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "--quiet", str(origin), str(work))
    for key, value in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
        _git(work, "config", key, value)
    (work / ".gitignore").write_bytes(b".claude/settings.json\n.claude/worktrees/\n")
    (work / ".worktreeinclude").write_bytes(b"# copied into a new worktree\n.claude/settings.json\n")
    (work / "README.md").write_bytes(b"seed\n")
    _git(work, "add", ".gitignore", ".worktreeinclude", "README.md")
    _git(work, "commit", "--quiet", "-m", "seed")
    _git(work, "push", "--quiet", "-u", "origin", "main")
    _git(work, "remote", "set-head", "origin", "main")
    (work / ".claude").mkdir()
    (work / ".claude" / "settings.json").write_bytes(b'{"hooks": {}}\n')
    _git(work, "config", "espalier.machine", "box")
    _git(work, "config", "extensions.worktreeConfig", "true")
    return work


def _worktree(work: Path, folder: str, *, name: str | None = None) -> Path:
    path = work / ".claude" / "worktrees" / folder
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(work, "worktree", "add", "--quiet", "-b", f"lane/{folder}", str(path), "origin/main")
    if name:
        _git(path, "config", "--worktree", "espalier.machine", name)
    if (work / "espalier.toml").is_file():   # tracked on a real tree, so every checkout holds it
        (path / "espalier.toml").write_bytes((work / "espalier.toml").read_bytes())
    return path


@pytest.fixture
def registry(seat, tmp_path, monkeypatch):
    """A session registry of this test's own: ``add(cwd, pid=...)``."""
    cfg = tmp_path / "claude-config"
    (cfg / "sessions").mkdir(parents=True)
    monkeypatch.setattr(seat.sync, "claude_config_dirs", lambda: [cfg])

    def add(cwd: Path, *, pid: int | None = None, entrypoint: str = "cli", kind: str = "interactive") -> int:
        pid = pid or os.getpid()
        (cfg / "sessions" / f"{pid}.json").write_text(json.dumps(
            {"pid": pid, "sessionId": f"s{pid}", "cwd": str(cwd), "kind": kind,
             "entrypoint": entrypoint, "startedAt": 1792045849132}), encoding="utf-8")
        return pid

    add.dir = cfg
    return add


@pytest.fixture
def no_claude(seat, monkeypatch):
    """Record the one spawn instead of running claude, as from a terminal of
    the operator's own (the suite's stdin is no terminal)."""
    monkeypatch.setattr(seat, "session_refusal", lambda: "", raising=False)
    calls: list[dict] = []
    real = seat.shutil.which
    # Only claude is faked: shutil.which is the one module every git runner shares.
    monkeypatch.setattr(seat.shutil, "which",
                        lambda name, path=None: "/fake/bin/claude" if name == "claude" else real(name, path=path))

    def call(argv, *, cwd, env):
        calls.append({"argv": argv, "cwd": cwd, "env": env})
        return 0

    monkeypatch.setattr(seat, "run_session", call)
    return calls


def _send(mod, path: Path, machine: str, type_: str, text: str, **kw) -> dict:
    message = mod.mail.new_message(machine, type_, text, **kw)
    mod.mail.send(path, message, say=lambda _s: None)
    return message


def _other_box(work: Path, machine: str) -> Path:
    """Another box's clone of the same origin, named ``machine``: what it
    sends lands on origin and reaches ``work`` only through a fetch."""
    other = work.parent / machine
    _git(work.parent, "clone", "--quiet", str(work.parent / "origin.git"), str(other))
    for key, value in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false"),
                       ("espalier.machine", machine)):
        _git(other, "config", key, value)
    return other


def _live_claims_from(seat, root: Path, machine: str) -> list[dict]:
    seat.mail.fetch_mail(root)
    by_machine, _ = seat.mail.read_mail(root)
    return [c for c in seat.mail.live_claims(by_machine) if c.get("from") == machine]


# -- list ----------------------------------------------------------------------------

class TestList:
    def test_the_clone_and_each_worktree_seat_are_named_with_who_is_in_them(self, seat, clone, registry):
        feat = _worktree(clone, "feat", name="box-feat")
        _worktree(clone, "plain")
        registry(clone)
        found, _note = seat.seats(clone, fetch=False)
        assert [(s.name, s.naming, s.where) for s in found] == [
            ("box", "clone", "the clone"), ("box-feat", "own", ".claude/worktrees/feat"),
            ("box-plain", "derived", ".claude/worktrees/plain")]
        assert [len(s.sessions) for s in found] == [1, 0, 0]
        assert [s.oracle for s in found] == ["registry"] * 3
        assert [s.removal for s in found] == ["", "removable", "removable"]
        text = seat.render(found, "")
        assert f"seat box -- the clone ({clone}), on main at" in text
        assert f"  sessions: pid {os.getpid()} (cli, started 2026-10-15 06:30Z)" in text
        assert "seat box-plain (name derived; SessionStart sets it) -- .claude/worktrees/plain" in text
        assert "  retire:   would remove it" in text and text.isascii()
        assert feat.is_dir()

    def test_claims_and_jobs_come_from_the_mail_refs(self, seat, clone, registry):
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat", paths=["README.md"])
        _send(seat, clone, "box", "assign", "build it", lane="lane/feat-2", seat="box-feat")
        found, _note = seat.seats(clone, fetch=True)
        by_name = {s.name: s for s in found}
        assert [c["re"]["lane"] for c in by_name["box-feat"].claims] == ["lane/feat"]
        assert [j["re"]["lane"] for j in by_name["box-feat"].jobs] == ["lane/feat-2"]
        assert by_name["box"].claims == [] and by_name["box"].jobs == []
        assert by_name["box-feat"].removal.startswith("its seat box-feat holds 1 live claim (lane/feat)")

    def test_a_registry_that_cannot_be_read_says_cannot_tell(self, seat, clone, monkeypatch):
        monkeypatch.setattr(seat.sync, "claude_config_dirs", lambda: [clone.parent / "no-such-config"])
        found, _note = seat.seats(clone, fetch=False)
        assert found[0].sessions is None
        assert "cannot tell (Claude Code's session registry could not be read in full" in seat.render(found, "")

    def test_the_cli_runs_from_inside_a_worktree_and_reports_the_whole_clone(self, seat, clone, registry,
                                                                             monkeypatch, capsys):
        feat = _worktree(clone, "feat", name="box-feat")
        monkeypatch.chdir(feat)
        assert seat.main(["list", "--json", "--no-fetch"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert [s["name"] for s in payload["seats"]] == ["box", "box-feat"]


# -- launch --------------------------------------------------------------------------

class TestTheSeatNamesSayAFailedRead:
    """A seat name git could not answer (a timeout, a config git cannot
    parse) is said, never taken for "no name": the clone's own name, which
    ``list``, ``launch`` and ``retire`` all read, and a worktree's own."""

    @staticmethod
    def _failures(seat):
        return (seat.mail.Unresolvable("git config took longer than 10s"),
                (128, "", "fatal: bad config line 3 in file .git/config"))

    @staticmethod
    def _clone_read_fails(seat, monkeypatch, failed):
        """The real clone read, with a git that fails it."""
        real = seat.mail.clone_machine

        def run(argv, **kw):
            if isinstance(failed, Exception):
                raise failed
            return failed
        monkeypatch.setattr(seat.mail, "clone_machine", lambda root, **kw: real(root, run=run))

    def test_an_unread_clone_name_lists_the_seats_and_says_why_nothing_was_read(self, seat, clone, registry,
                                                                              monkeypatch):
        """Dies to the failed read taken for a clone that names no machine:
        the clone listed as unnamed, its worktrees given no seat, and the
        claims and jobs skipped in silence."""
        _worktree(clone, "plain")
        for failed in self._failures(seat):
            self._clone_read_fails(seat, monkeypatch, failed)
            found, note = seat.seats(clone, fetch=False)
            assert found[0].naming == "unread" and seat.mail.MACHINE_UNREAD in found[0].naming_note, found[0]
            assert found[1].naming == "unread" and found[1].name == "", found[1]
            assert "clone's machine name could not be read" in note and "claims or jobs" in note, note
            assert "(seat name unread: git config could not be read" in seat.render(found, note)

    def test_an_unread_clone_name_refuses_resolve_and_retire_without_the_naming_advice(self, seat, clone,
                                                                                    monkeypatch):
        """Dies to the refusal that offered `git config espalier.machine
        <name>`, which in a worktree renames the clone and fails the same way
        on a config git cannot parse; and to retire taking a seat for one that
        is not the clone when the clone's name is unknown."""
        _worktree(clone, "feat", name="box-feat")
        for failed in self._failures(seat):
            self._clone_read_fails(seat, monkeypatch, failed)
            with pytest.raises(seat.Refused) as caught:
                seat.resolve(clone, "box-feat")
            said = str(caught.value)
            assert seat.mail.MACHINE_UNREAD in said and "names it" not in said, said
            with pytest.raises(seat.Refused) as caught:
                seat.cmd_retire(clone, "box-feat", dry_run=True, fetch=False)
            said = str(caught.value)
            assert "cannot be told from the clone itself" in said and seat.mail.MACHINE_UNREAD in said, said

    def test_a_hand_set_name_the_channel_refuses_is_not_replaced_by_a_derived_one(self, seat, clone, registry):
        """A worktree whose own config holds a value the channel does not take.
        SessionStart never names it (it has a name of its own), so a derived
        name would stand for a seat nothing answers. Dies to the refused value
        read as "not set" (the derived name offered, and resolve handing the
        worktree over under it), the board having said the opposite."""
        feat = _worktree(clone, "feat")
        _git(feat, "config", "--worktree", "espalier.machine", "Air-2")
        found, _note = seat.seats(clone, fetch=False)
        row = next(s for s in found if s.path == str(feat))
        assert row.naming == "unnamed" and row.name == "" and seat.mail.NAME_REFUSED in row.naming_note, row
        with pytest.raises(seat.Refused):
            seat.resolve(clone, "box-feat")

    def test_launch_refuses_when_the_worktrees_own_name_cannot_be_read(self, seat, clone, registry, monkeypatch):
        """The launch's own check, after naming: dies to the unread name read
        as "does not answer the seat", which names the wrong cause. The
        registry is the test's own: on a host with no readable one (every CI
        runner) the occupancy check refuses first and the name read is never
        reached."""
        feat = _worktree(clone, "feat", name="box-feat")
        monkeypatch.setattr(seat, "resolve", lambda root, s: seat.Target(s, feat, True, False))
        monkeypatch.setattr(seat.mail, "name_this_worktree", lambda path, **kw: (None, ""))
        monkeypatch.setattr(seat, "_own_name",
                            lambda path: ("", "unread", "git config could not be read (git exited 128)"))
        with pytest.raises(seat.Refused) as caught:
            seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=True)
        said = str(caught.value)
        assert "own seat name could not be read" in said and "fix it first" in said, said

    def test_a_worktree_whose_own_name_is_unread_is_not_given_a_derived_one(self, seat, clone, registry):
        """A config git cannot parse in the worktree's own config. Dies to the
        failed read taken for "no name of its own": the derived name then
        stood for the seat, and resolve handed that worktree to a launch or a
        retire of a name it may not answer."""
        feat = _worktree(clone, "feat", name="box-feat")
        (clone / ".git" / "worktrees" / "feat" / "config.worktree").write_bytes(b"[espalier\n")
        found, _note = seat.seats(clone, fetch=False)
        row = next(s for s in found if s.path == str(feat))
        assert row.naming == "unread" and row.name == "" and seat.mail.MACHINE_UNREAD in row.naming_note, row
        with pytest.raises(seat.Refused) as caught:
            seat.resolve(clone, "box-feat")
        assert "could not be read" in str(caught.value) and str(feat) in str(caught.value), caught.value


class TestASeatNameTwoCheckoutsAnswer:
    """A seat name two checkouts answer (DEF-4125's shape: a stale twin a
    seat's process made, answering that seat's name) is refused by every verb
    that takes a seat, naming each checkout with its branch, head and
    sessions, and the rename only where one window alone says which is the
    seat, so none picks the one ``git worktree list`` shows first: ``launch`` would
    start a second writer on the seat's mail ref, ``brief`` and ``tick``
    compose from the twin, ``retire`` releases claims the live checkout works.
    Dies to: ``resolve`` returning the first worktree whose name matches
    without reading the rest (it refuses in neither listing order)."""

    @staticmethod
    def _twins(clone):
        return _worktree(clone, "a", name="box-x"), _worktree(clone, "b", name="box-x")

    @staticmethod
    def _rename(path: Path) -> str:
        return f'git -C "{path.as_posix()}" config --worktree espalier.machine <name>'

    @staticmethod
    def _static(said: str, clone: Path) -> str:
        """The refusal with the scratch paths taken out: a temp folder can
        hold any character the host's user name does, the words cannot."""
        return said.replace(str(clone.parent), "").replace(clone.parent.as_posix(), "")

    def test_one_live_checkout_gets_the_rename_for_each_other_one(self, seat, clone, registry):
        """Dies to: a rename offered for every answering checkout (the live
        one's included, which renames the seat out from under its session),
        and to the two-command pair chained with `&&`, which Windows
        PowerShell 5.1 refuses to parse."""
        a, b = self._twins(clone)
        registry(a)
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box-x")
        said = str(caught.value)
        assert "answered by 2 checkouts" in said and "one mail ref" in said, said
        assert f"only {a.as_posix()} holds a session; if it is the seat" in said, said
        assert self._rename(b) in said and f'git -C "{a.as_posix()}"' not in said and "&&" not in said, said
        assert f"{a.as_posix()} on lane/a at" in said and f"{b.as_posix()} on lane/b at" in said, said
        assert str(a) == a.as_posix() or str(a) not in said, said
        assert self._static(said, clone).isascii(), said

    def test_no_live_checkout_is_the_operators_call_with_the_shape_once(self, seat, clone, registry):
        """Neither holds a session, so which is the seat is not the driver's
        to read: no checkout is named for a rename, the command's shape is
        given once for the operator to run, and each checkout's branch and
        head to read it by. Dies to: a rename printed for a checkout picked by
        listing order."""
        twins = self._twins(clone)
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box-x")
        said = str(caught.value)
        assert "the operator's call (none of them holds a session)" in said, said
        assert said.count("git -C") == 1 and 'git -C "<checkout>" config --worktree' in said, said
        assert "each checkout that is not the seat" in said, said
        for path in twins:
            assert (f"{path.as_posix()} on lane/{path.name} at {_out(path, 'rev-parse', '--short=7', 'HEAD')}"
                    in said), said
        assert self._static(said, clone).isascii(), said

    @pytest.mark.parametrize("case, why", [
        ("marker", "a session there is named only by a session marker"),
        ("mixed", "a session there is named only by a session marker"),
        ("background", "a session there is a background one Claude Code's daemon resumed"),
        ("headless", "a session there is no window ('sdk-cli', where a window is cli or claude-vscode)"),
        ("caller", "a session there is the one asking"),
    ], ids=["marker", "mixed", "background", "headless", "caller"])
    def test_a_lone_session_that_is_weak_evidence_gets_no_rename(self, seat, clone, registry, monkeypatch,
                                                                case, why):
        """One checkout alone holds sessions, but they do not say it is the
        seat: a marker outlives its window (``mixed``: one beside a window the
        registry lists, a session that window is not), the daemon resumes an
        old session wherever it was, a headless run registers as kind
        interactive and can be started from any checkout, and the asker is
        wherever it asked from. Dies to: the rename given for the other
        checkout on any lone session, which renames the live seat out from
        under its window."""
        a, b = self._twins(clone)
        if case in ("marker", "mixed"):
            marker = {"session_id": "m1", "pid": 999_999_999 if case == "mixed" else os.getpid(), "cwd": str(a)}
            monkeypatch.setattr(seat.sync, "_default_marker_reader", lambda: (
                lambda tree: [marker] if seat.sync._norm(tree) == seat.sync._norm(a) else []))
        if case == "mixed":
            registry(a)
        elif case == "background":
            registry(a, kind="background")
        elif case == "headless":
            registry(a, entrypoint="sdk-cli")
        elif case == "caller":
            monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", f"s{registry(a)}")
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box-x")
        said = str(caught.value)
        assert f"the operator's call (only {a.as_posix()} holds a session, and {why})" in said, said
        assert self._rename(b) not in said and said.count("git -C") == 1, said
        assert f"{a.as_posix()} on lane/a at" in said and " live session(s): pid" in said, said

    def test_a_caller_in_another_checkout_does_not_hold_the_rename_back(self, seat, clone, registry, monkeypatch):
        """Run inside a session, as `retire` and `launch --print` are: the
        asker's own window is in the clone, which answers another name, and
        the seat's window is in one twin. Dies to: any known caller read as
        weak evidence, wherever it is."""
        a, b = self._twins(clone)
        registry(a)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", f"s{registry(clone, pid=os.getppid())}")
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box-x")
        said = str(caught.value)
        assert f"only {a.as_posix()} holds a session; if it is the seat" in said and self._rename(b) in said, said

    def test_the_askers_own_window_in_the_clone_holds_no_twins_rename_back(self, seat, clone, registry,
                                                                          monkeypatch):
        """The asker's window in the clone, a worktree named back to the
        clone's name: the clone's own name is the main checkout's by
        construction (DEF-3098), so who asks from where is no evidence either
        way, and the worktree gets its rename. Dies to: the clone's name read
        like any other, which made this the operator's call with no command."""
        a = _worktree(clone, "a", name="box")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", f"s{registry(clone)}")
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box")
        said = str(caught.value)
        assert self._rename(a) in said and f'git -C "{clone.as_posix()}"' not in said, said
        assert "the operator's call" not in said, said

    def test_a_worktree_named_back_to_the_clones_name_is_refused(self, seat, clone, registry, monkeypatch,
                                                                 capsys):
        """The clone's own name was answered before any worktree was read, so
        a worktree named back to it was never counted (driven: `launch box
        --print` exit 0). Dies to: that early return kept."""
        a = _worktree(clone, "a", name="box")
        registry(clone)
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box")
        said = str(caught.value)
        assert "answered by 2 checkouts" in said, said
        assert f"the main checkout ({clone.as_posix()}) answers its clone's name by construction" in said, said
        assert self._rename(a) in said, said
        monkeypatch.chdir(a)
        assert seat.main(["launch", "box", "--print"]) == 1
        assert "answered by 2 checkouts" in capsys.readouterr().err

    def test_the_clone_is_never_handed_a_rename(self, seat, clone, registry):
        """The live session in a worktree named back to the clone's name: a
        rename of the clone moves every seat name derived from it, so the main
        checkout is the seat by construction and the worktree, live or not, is
        the one renamed (DEF-3098), after the words that its live session
        releases its claims from it first: renamed under it, that session's
        next send goes out under the new name and leaves its claims under the
        clone's where it can no longer release them (the second review). Dies
        to: the clone given a rename like any session-less checkout, the
        operator's call where the seat is known, and a bare rename of a
        checkout a window is live in."""
        a = _worktree(clone, "a", name="box")
        registry(a)
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box")
        said = str(caught.value)
        assert f'git -C "{clone.as_posix()}"' not in said and "the operator's call" not in said, said
        assert (f"{a.as_posix()} was named back to the clone's name; a session in it writes under the clone's name "
                "now: release its claims from it first") in said, said
        assert f"or end that session; then rename it:\n{self._rename(a)}" in said, said

    def test_brief_of_the_clones_name_from_the_clone_composes_beside_a_twin(self, seat, clone, registry,
                                                                            monkeypatch, capsys):
        """The clone's own seat runs `brief <its name>` from the clone while a
        worktree answers that name too: composed from the clone, never
        refused; `launch` from the same place stays strict. Dies to: the
        clone left out of the checkouts the cwd read answers for."""
        _worktree(clone, "a", name="box")
        monkeypatch.chdir(clone)
        assert seat.main(["brief", "box"]) == 0
        assert capsys.readouterr().out == seat.compose_brief(clone, "box", clone).text + "\n"
        assert seat.main(["launch", "box", "--print"]) == 1
        assert "answered by 2 checkouts" in capsys.readouterr().err

    def test_the_clones_name_beside_a_worktree_whose_name_is_unread_is_not_picked(self, seat, clone):
        """The unread worktree may be one named back to the clone's own name,
        so the clone's seat is not resolved past it either. Dies to: the
        clone's name answered before the worktrees were read."""
        _worktree(clone, "b", name="box-b")
        (clone / ".git" / "worktrees" / "b" / "config.worktree").write_bytes(b"[espalier\n")
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box")
        assert "could not be read" in str(caught.value) and "'box'" in str(caught.value), caught.value

    @pytest.mark.parametrize("case, reason", [
        ("untold", "who is in each could not be told"),
        ("two-live", "2 of them hold sessions"),
        ("ext-unread", "whether per-worktree config is on could not be read (git exited 128)"),
    ], ids=["untold", "two-live", "ext-unread"])
    def test_a_rename_is_given_only_where_one_live_checkout_is_told(self, seat, clone, monkeypatch, case, reason):
        """The rename needs one live checkout among checkouts all told, and a
        clone where a ``--worktree`` set can land; where it can, the shape is
        still given once, naming no checkout. Dies to: a checkout whose
        occupancy cannot be told read as empty (``untold``: the other one would
        be named live), the second live one renamed (``two-live``), and the set
        printed where whether per-worktree config is on went unread at the
        remedy's own read (``ext-unread``: the worktrees' names read, so only
        that read is failed). The live rows are the registry's, so only the
        case's own fact keeps the rename back."""
        a, b = self._twins(clone)
        live = seat.sync.Occupancy([{"pid": 1, "source": "registry", "kind": "interactive", "entrypoint": "cli"}],
                                   "registry")
        states = {"untold": (live, seat.sync.Occupancy(None, "", "cannot tell")), "two-live": (live, live)}
        first, second = states.get(case, (live, seat.sync.Occupancy([], "registry")))
        monkeypatch.setattr(seat.sync, "occupancy", lambda path, **kw: first if path == a else second)
        if case == "ext-unread":
            real = seat.mail._worktree_config
            monkeypatch.setattr(seat.mail, "_worktree_config", lambda root, **kw: (
                (None, "git exited 128") if Path(root) == clone else real(root, **kw)))
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box-x")
        said = str(caught.value)
        assert f"the operator's call ({reason}" in said, said
        assert self._rename(a) not in said and self._rename(b) not in said, said
        assert said.count("git -C") == (0 if case == "ext-unread" else 1), said

    @pytest.mark.parametrize("live", [True, False], ids=["one-live", "none-live"])
    def test_two_folders_one_derived_name_with_per_worktree_config_off(self, seat, clone, registry, live):
        """With per-worktree config off no worktree holds a name of its own,
        so the one twin left is two folders that derive one name; a
        ``--worktree`` set fails there, and that is said beside any other
        reason, so a set written by hand is not taken for the fix. Dies to:
        the rename printed with the config off (``one-live``), and the config
        said only where no other reason holds (``none-live``)."""
        _git(clone, "config", "extensions.worktreeConfig", "false")
        dotted, dashed = _worktree(clone, "x.y"), _worktree(clone, "x-y")
        if live:
            registry(dotted)
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box-x-y")
        said = str(caught.value)
        first = "" if live else "none of them holds a session; "
        assert f"the operator's call ({first}per-worktree config is off in this clone" in said, said
        assert "git -C" not in said and dashed.as_posix() in said, said

    def test_a_derived_name_and_an_own_name_that_meet_are_refused(self, seat, clone):
        """One worktree's own name is another's derived one: both answer it.
        A coverage pin (the read of every worktree already counts both)."""
        own = _worktree(clone, "a", name="box-b")
        derived = _worktree(clone, "b")
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box-b")
        said = str(caught.value)
        assert "answered by 2 checkouts" in said and own.as_posix() in said and derived.as_posix() in said, said

    def test_brief_and_tick_from_inside_an_answering_checkout_compose_from_it(self, seat, clone, registry,
                                                                              monkeypatch, capsys):
        """The live seat's own `brief <seat>` (the handoff's re-prime, the
        banner's Orders line) and `tick <seat>` read the checkout they run in
        when it answers the name, so a stale twin never stops them; `launch`
        and `retire` stay strict. Dies to: every named read sent through
        resolve. The twin names no dispatcher, so a brief from it reads apart."""
        a, _b = self._twins(clone)
        (a / "espalier.toml").write_bytes(b'dispatcher = "air"\n')
        monkeypatch.chdir(a)
        assert seat.main(["brief", "box-x"]) == 0
        out = capsys.readouterr().out
        assert out == seat.compose_brief(clone, "box-x", a).text + "\n" and "the dispatcher air" in out, out
        assert seat.main(["tick", "box-x"]) == 0
        assert capsys.readouterr().out == seat.compose_brief(clone, "box-x", a).tick + "\n"
        for verb in (["launch", "box-x", "--print"], ["retire", "box-x", "--dry-run", "--no-fetch"]):
            assert seat.main(verb) == 1, verb
            assert "answered by 2 checkouts" in capsys.readouterr().err, verb

    def test_an_empty_seat_name_is_refused(self, seat, clone, registry):
        """An empty name matched every worktree that answers none (a refused
        value, an unread or a gone one): resolve handed one over. Dies to:
        the guard dropped."""
        feat = _worktree(clone, "feat")
        _git(feat, "config", "--worktree", "espalier.machine", "Air-2")
        with pytest.raises(seat.Refused) as caught:
            seat.resolve(clone, "")
        assert "no seat named" in str(caught.value), caught.value

    @pytest.mark.parametrize("verb", [["brief"], ["tick"], ["launch", "--print"], ["retire", "--dry-run"]],
                             ids=["brief", "tick", "launch", "retire"])
    def test_every_verb_that_takes_a_seat_refuses_it(self, seat, clone, registry, monkeypatch, capsys, verb):
        self._twins(clone)
        monkeypatch.chdir(clone)
        assert seat.main([verb[0], "box-x", *verb[1:]]) == 1
        err = capsys.readouterr().err
        assert "answered by 2 checkouts" in err, err

    def test_retire_releases_nothing_and_never_calls_the_worktree_gone(self, seat, clone, registry):
        """Dies to: retire's recovery from a plain refusal (the gone-worktree
        recipe) taking this one, which told the operator to add a third
        checkout under the name and release the live seat's claims. The claim
        goes out before the twin exists: from a twin the writer refuses it
        (DEF-3100)."""
        a = _worktree(clone, "a", name="box-x")
        _send(seat, a, "box-x", "claim", "live", lane="lane/x")
        b = _worktree(clone, "b", name="box-x")
        with pytest.raises(seat.Undecided) as caught:
            seat.cmd_retire(clone, "box-x", dry_run=False, fetch=True)
        said = str(caught.value)
        assert "answered by 2 checkouts" in said and "worktree is gone" not in said, said
        assert a.is_dir() and b.is_dir() and len(_live_claims_from(seat, clone, "box-x")) == 1

    def test_the_tick_with_no_seat_named_is_composed_from_this_checkout(self, seat, clone, monkeypatch, capsys):
        """The loop's own call: ``tick`` with no seat reads the checkout it
        runs in, never ``resolve``, so a stale twin never stops a live seat's
        loop. Dies to: the no-seat path routed through ``resolve``."""
        a, _b = self._twins(clone)
        monkeypatch.chdir(a)
        assert seat.main(["tick"]) == 0
        assert capsys.readouterr().out == seat.compose_brief(clone, "box-x", a).tick + "\n"

    def test_a_match_beside_a_worktree_whose_name_is_unread_is_not_picked(self, seat, clone):
        """The unread name is the same read left out: it may be the twin.
        Dies to: the first match returned before every name was read, which
        resolved past an unread worktree in any listing order."""
        _worktree(clone, "a", name="box-x")
        _worktree(clone, "b", name="box-b")
        (clone / ".git" / "worktrees" / "b" / "config.worktree").write_bytes(b"[espalier\n")
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box-x")
        assert "could not be read" in str(caught.value), caught.value

    def test_retire_names_an_unread_seat_name_as_unread_never_as_gone(self, seat, clone, registry):
        """Dies to: retire's gone-worktree recipe given for a worktree that is
        there and whose name git could not read."""
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, feat, "box-feat", "claim", "live", lane="lane/feat")
        (clone / ".git" / "worktrees" / "feat" / "config.worktree").write_bytes(b"[espalier\n")
        with pytest.raises(seat.Undecided) as caught:
            seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True)
        said = str(caught.value)
        assert "could not be read" in said and "worktree is gone" not in said, said
        assert feat.is_dir()


def _outside(work: Path, folder: str, *, name: str | None = None) -> Path:
    """A worktree outside ``.claude/worktrees/``, as ``git worktree add`` makes
    one for a reviewer's scratch copy (air's cf1b9f; this box's ``C:/tmp/wt*``)."""
    path = work.parent / folder
    _git(work, "worktree", "add", "--quiet", "-b", f"lane/{folder}", str(path), "origin/main")
    if name:
        _git(path, "config", "--worktree", "espalier.machine", name)
    return path


class TestEveryListedCheckoutIsRead:
    """DEF-3098: the resolver reads every checkout git lists, each by the name
    it writes under (``mail.checkout_names``, the reader the board reads too),
    so a twin the board flags is one the seat driver refuses. Dies to: the
    population taken from ``.claude/worktrees/`` (the outside twin resolved
    past in silence), or the main checkout read at the clone's ``--local``
    scope (one name to the resolver, another to the writer)."""

    def test_a_twin_outside_the_worktrees_folder_is_refused(self, seat, clone, registry):
        """The row's probe shape: one inside, one outside, both ``box-x``."""
        inside, outside = _worktree(clone, "a", name="box-x"), _outside(clone, "outside", name="box-x")
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box-x")
        said = str(caught.value)
        assert "answered by 2 checkouts" in said and "one mail ref" in said, said
        assert f"{inside.as_posix()} on lane/a at" in said and f"{outside.as_posix()} on lane/outside at" in said, said

    def test_a_seat_named_outside_the_folder_resolves_to_its_checkout(self, seat, clone):
        outside = _outside(clone, "solo", name="box-solo")
        target = seat.resolve(clone, "box-solo")
        assert (target.path, target.exists, target.is_clone) == (outside, True, False), target

    def test_a_worktree_named_back_to_the_clone_outside_the_folder_is_its_twin(self, seat, clone, registry):
        """A ``--worktree`` setting of the clone's own name writes under the
        clone's ref, with no session or with one (DEF-3097's rule, now read
        outside the folder too). Dies to: the outside worktree skipped."""
        back = _outside(clone, "back", name="box")
        registry(clone)
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box")
        said = str(caught.value)
        assert f'git -C "{back.as_posix()}" config --worktree espalier.machine <name>' in said, said
        assert f'git -C "{clone.as_posix()}"' not in said, said

    def test_a_nameless_worktree_is_the_clones_twin_only_while_a_session_holds_it(self, seat, clone, registry):
        """A worktree with no name of its own writes under the clone's name,
        but only a session writes: a dormant one (a reviewer's scratch copy)
        is no twin, while one a session holds is, inside the folder or out,
        and one under the folder keeps its derived launch name. Dies to: every
        nameless worktree read as a twin (the clone refused beside each
        scratch copy), or none (a live writer on the clone's ref unseen)."""
        scratch, plain = _outside(clone, "scratch"), _worktree(clone, "plain")
        assert seat.resolve(clone, "box").path == clone
        assert seat.resolve(clone, "box-plain").path == plain
        # A launch targets a derived name only under the folder (DEF-3098's
        # second reviews): `launch box-scratch` makes .claude/worktrees/scratch
        # rather than start a session in someone's stale copy.
        target = seat.resolve(clone, "box-scratch")
        assert (target.path, target.exists) == (clone / ".claude" / "worktrees" / "scratch", False), target
        for live in (scratch, plain):
            pid = registry(live)
            with pytest.raises(seat.Undecided) as caught:
                seat.resolve(clone, "box")
            assert f"{live.as_posix()} on lane/" in str(caught.value), caught.value
            (registry.dir / "sessions" / f"{pid}.json").unlink()
        assert seat.resolve(clone, "box-plain").path == plain

    def test_the_main_checkout_answers_its_own_worktree_name(self, seat, clone):
        """A ``--worktree`` name set in the main checkout is the name its mail
        is written under (the writer's effective read), so the resolver reads
        the same; asked for the clone's name it is refused by name, and the
        derived names stay built on the clone's. Dies to: the main checkout
        resolved by the clone's ``--local`` name."""
        # Added first: `git worktree add` copies the per-worktree config of the
        # checkout it runs in (driven on git 2.52.0), so one this fixture added
        # after would answer box-main too (the launcher unsets the copy: pinned
        # by test_a_name_git_copies_from_the_main_checkout_is_unset_at_create).
        plain = _worktree(clone, "plain")
        _git(clone, "config", "--worktree", "espalier.machine", "box-main")
        target = seat.resolve(clone, "box-main")
        # The clone's seat by its path, never by the name asked for.
        assert (target.path, target.is_clone) == (clone, True), target
        with pytest.raises(seat.Refused) as caught:
            seat.resolve(clone, "box")
        assert not isinstance(caught.value, seat.Undecided), caught.value
        assert "the main checkout answers 'box-main', not its clone's name 'box'" in str(caught.value), caught.value
        assert seat.resolve(clone, "box-plain").path == plain

    def test_the_list_shows_a_named_or_live_worktree_outside_the_folder(self, seat, clone, registry):
        """So the twin refusal's pointer (`seat.py list`) shows the twin; a
        dormant one with no name of its own is left out, and none outside the
        folder is ever offered for removal. Dies to: the listing kept to the
        folder."""
        named, back = _outside(clone, "named", name="box-n"), _outside(clone, "back", name="box")
        dormant, live = _outside(clone, "dormant"), _outside(clone, "live")
        registry(live)
        found, _note = seat.seats(clone, fetch=False)
        rows = {s.path: (s.name, s.naming, s.where, s.removal) for s in found}
        assert str(dormant) not in rows, rows
        assert rows[str(named)] == ("box-n", "own", named.as_posix(), seat.OUTSIDE_KEPT), rows
        assert rows[str(back)] == ("box", "own", back.as_posix(), seat.OUTSIDE_KEPT), rows
        assert rows[str(live)] == ("box", "inherited", live.as_posix(), seat.OUTSIDE_KEPT), rows
        text = seat.render(found, "")
        assert "(no name of its own: it answers its clone's)" in text and "kept -- outside .claude/worktrees/" in text
        assert text.isascii()

    def test_retire_refuses_a_seat_outside_the_folder_before_anything_is_sent(self, seat, clone, registry):
        solo = _outside(clone, "solo", name="box-solo")
        sent = _send(seat, solo, "box-solo", "claim", "a lane", lane="lane/solo")
        with pytest.raises(seat.Refused) as caught:
            seat.cmd_retire(clone, "box-solo", dry_run=False, fetch=True)
        said = str(caught.value)
        assert seat.OUTSIDE_KEPT in said and "nothing was released or removed" in said, said
        assert f"--ack {sent['id']}" in said, said
        assert solo.is_dir()

    def test_a_bare_clone_is_stood_for_by_the_checkout_it_runs_from(self, seat, clone, registry):
        """A bare clone's first listed entry is the repository itself, where no
        session runs: the checkout the driver runs from stands for the clone,
        as before DEF-3098, and is no twin of itself while a session holds it.
        Dies to: the bare repository's folder handed over as the clone's seat
        (a launch where there is no work tree), or that checkout counted twice."""
        bare = clone.parent / "box.git"
        _git(clone.parent, "clone", "--quiet", "--bare", str(clone.parent / "origin.git"), str(bare))
        _git(bare, "config", "espalier.machine", "box")
        here = clone.parent / "bare-here"
        _git(bare, "worktree", "add", "--quiet", str(here), "main")
        registry(here)
        target = seat.resolve(here, "box")
        assert (target.path, target.exists, target.is_clone) == (here, True, True), target

    def test_an_unread_copy_outside_the_folder_refuses_with_its_makers_remedy(self, seat, clone):
        """One copy made by hand whose name git cannot read refuses every seat
        name (it may be the twin), so the refusal says whose it is to fix: no
        seat driver made it. Dies to: the bare retry, which a config git
        cannot parse never answers."""
        scratch = _outside(clone, "scratch")
        _worktree(clone, "a", name="box-a")
        (clone / ".git" / "worktrees" / "scratch" / "config.worktree").write_bytes(b"[espalier\n")
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box-a")
        said = str(caught.value)
        assert "could not be read" in said and scratch.name in said, said
        assert "it is outside .claude/worktrees/, so no seat driver made it: fix its config" in said, said

    def test_a_nameless_worktree_nobody_can_see_into_refuses_with_the_registrys_remedy(self, seat, clone,
                                                                                         monkeypatch):
        """Who is in a worktree that answers the clone's name could not be told
        (the registry unread): the remedy is the registry's, never git's. Dies
        to: the git retry printed for a read git answered."""
        _outside(clone, "scratch")
        monkeypatch.setattr(seat.sync, "live_sessions", lambda *a, **k: None)
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box")
        said = str(caught.value)
        assert "Claude Code's session registry could not be read in full" in said, said
        assert "retry once Claude Code's session registry reads in full" in said, said
        assert seat.mail.RETRY_HINT not in said, said

    def test_the_main_checkouts_unread_name_refuses_every_seat_with_gits_remedy(self, seat, clone, monkeypatch):
        """A coverage pin of the arm no real git reaches alone (a main
        checkout's config git cannot parse fails its listing too): the main
        checkout's name unread resolves no seat, its own or a worktree's. Dies
        to: the main checkout skipped when its read fails."""
        _worktree(clone, "a", name="box-a")
        real = seat.mail.checkout_names

        def main_unread(root, **kw):
            rows = real(root, **kw)
            rows[0].update(name="", unread=f"{seat.mail.MACHINE_UNREAD} (git config took longer than 10s)")
            return rows
        monkeypatch.setattr(seat.mail, "checkout_names", main_unread)
        for name in ("box", "box-a"):
            with pytest.raises(seat.Undecided) as caught:
                seat.resolve(clone, name)
            said = str(caught.value)
            assert f"the seat name of {clone} (" in said and seat.mail.RETRY_HINT in said, (name, said)

    def test_a_dormant_copy_named_back_beside_an_idle_main_checkout_gets_its_rename(self, seat, clone, registry):
        """The clone's own name is the main checkout's by construction, so it
        is never the operator's call there, whoever holds a session (DEF-3098's
        review). Dies to: the clone's name read like any other name, which with
        no session anywhere named no checkout to rename."""
        back = _outside(clone, "back", name="box")
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box")
        said = str(caught.value)
        assert (f"{back.as_posix()} was named back to the clone's name; rename it:\n"
                f'git -C "{back.as_posix()}" config --worktree espalier.machine <name>') in said, said
        assert f'git -C "{clone.as_posix()}"' not in said and "the operator's call" not in said, said

    def test_a_nameless_live_copy_gets_the_boards_own_naming_text(self, seat, clone, registry):
        """A worktree with no name of its own that a session holds writes
        under the clone's name: its remedy is naming it, and the words are the
        board's (``mail.naming_steps`` read for a reader in another checkout,
        as ``board.read_sessions`` calls it), never "took the clone's own name".
        Dies to: the operator's call where the main checkout is the seat."""
        copy = _outside(clone, "copy")
        registry(copy)
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box")
        said = str(caught.value)
        row = next(r for r in seat.mail.checkout_names(clone) if Path(r["path"]).name == "copy")
        naming = seat.mail.naming_steps(Path(row["path"]), at=row["path"])
        assert naming.count("\n") == 1 and naming.endswith("config --worktree espalier.machine <name>"), naming
        assert (f"{copy.as_posix()} has no name of its own; a session in it writes under the clone's name now: "
                "release its claims from it first") in said, said
        assert f"or end that session; then name it, one command a line:\n{naming}" in said, said
        assert said.endswith(naming), said
        assert f'git -C "{clone.as_posix()}"' not in said and "took the clone's own name" not in said, said

    def test_a_seat_beside_a_dormant_copy_of_its_folder_name_resolves_to_the_seat(self, seat, clone):
        """A copy made by hand elsewhere with a seat's folder name is no twin:
        the seat holds the name, and the copy's next session is refused it
        (``mail.name_this_worktree``: the name is taken), so the launch, brief
        and retire of the seat are not refused for it. Dies to: a derived name
        read outside ``.claude/worktrees/`` (DEF-3098's second reviews: a false
        twin, and a launch into someone's stale copy)."""
        inside = _worktree(clone, "scratch", name="box-scratch")
        copy = clone.parent / "elsewhere" / "scratch"
        _git(clone, "worktree", "add", "--quiet", "--detach", str(copy), "origin/main")
        target = seat.resolve(clone, "box-scratch")
        assert (target.path, target.is_clone) == (inside, False), target
        name, said = seat.mail.name_this_worktree(copy)
        assert name is None and "is taken by" in said, said

    def test_every_listed_checkout_sends_under_the_name_the_reader_gives_it(self, seat, clone):
        """The reader's name is the writer's: a send from each listed checkout
        as the name ``mail.checkout_names`` gives it lands on that name's ref
        (``send`` refuses a message from any other name). Dies to: either side
        read at another scope (FM-W4: the agreement was a docstring)."""
        _worktree(clone, "a", name="box-a")
        _outside(clone, "out")
        _outside(clone, "named", name="box-n")
        _git(clone, "config", "--worktree", "espalier.machine", "box-main")
        rows = seat.mail.checkout_names(clone)
        assert sorted(r["name"] for r in rows) == ["box", "box-a", "box-main", "box-n"], rows
        origin = clone.parent / "origin.git"
        for row in rows:
            sent = _send(seat, Path(row["path"]), row["name"], "note", f"from {Path(row['path']).name}")
            held = _git(origin, "show", f"{seat.mail.ref_for(row['name'])}:mail.jsonl").stdout
            assert sent["id"] in held, (row, held)

    def test_the_twin_refusal_reads_each_checkouts_sessions_once(self, seat, clone, registry, monkeypatch):
        """The resolver counted a nameless copy a twin for its session, then
        the refusal read again and could call it one with none. Dies to: the
        refusal's own second read."""
        copy = _outside(clone, "copy")
        registry(copy)
        real, reads = seat.sync.occupancy, []

        def gone_on_the_second_read(path, **kw):
            reads.append(seat.sync._norm(path))
            if reads.count(seat.sync._norm(copy)) > 1 and seat.sync._norm(path) == seat.sync._norm(copy):
                return seat.sync.Occupancy([], "registry")
            return real(path, **kw)
        monkeypatch.setattr(seat.sync, "occupancy", gone_on_the_second_read)
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box")
        said = str(caught.value)
        assert reads.count(seat.sync._norm(copy)) == 1, reads
        assert f"{copy.as_posix()} on lane/copy at" in said and "1 live session(s)" in said, said

    def test_a_name_git_copies_from_the_main_checkout_is_unset_at_create(self, seat, clone, registry, no_claude,
                                                                         capsys):
        """`git worktree add` copies the per-worktree config of the checkout it
        runs in (driven on git 2.52.0), so a main checkout with a ``--worktree``
        name of its own handed it to the seat the launcher made, a twin of the
        main by construction. Dies to: the copy left (the launch refused: the
        new worktree answers box-main, not box-3)."""
        _git(clone, "config", "--worktree", "espalier.machine", "box-main")
        probe = _worktree(clone, "probe")
        if _git(probe, "config", "--worktree", "--get", "espalier.machine", check=False).stdout.strip() != "box-main":
            pytest.skip("this git does not copy the per-worktree config at worktree add (git 2.36 and later do)")
        assert seat.cmd_launch(clone, "box-3", [], maintenance=False, unchecked=False, print_only=False,
                               brief=False, mod=False) == 0
        made = clone / ".claude" / "worktrees" / "3"
        assert _out(made, "config", "--worktree", "--get", "espalier.machine") == "box-3"
        assert _out(clone, "config", "--worktree", "--get", "espalier.machine") == "box-main"
        out = capsys.readouterr().out
        assert "unset the seat name 'box-main' git copied into" in out and "named this worktree box-3" in out, out

    def test_a_worktree_holding_the_main_checkouts_copied_name_is_told_the_unset(self, seat, clone):
        """A launch whose unset failed leaves its worktree answering the main
        checkout's own name (git copied it in); the next launch is told the
        unset, never to launch that name, which would be the main checkout's
        twin. Dies to: the plain "launch <its name>" hint."""
        _git(clone, "config", "--worktree", "espalier.machine", "box-main")
        made = _worktree(clone, "3")
        if _git(made, "config", "--worktree", "--get", "espalier.machine", check=False).stdout.strip() != "box-main":
            pytest.skip("this git does not copy the per-worktree config at worktree add (git 2.36 and later do)")
        with pytest.raises(seat.Refused) as caught:
            seat.resolve(clone, "box-3")
        said = str(caught.value)
        assert f'git -C "{made.as_posix()}" config --worktree --unset-all espalier.machine' in said, said
        assert "launch box-main" not in said, said

    def test_the_clones_name_where_per_worktree_config_is_unread_is_the_operators_call(self, seat, clone,
                                                                                        registry, monkeypatch):
        """The per-twin commands need per-worktree config read: where it went
        unread, the clone's name is the operator's call too, and no command is
        given. Dies to: the guard dropped (a --worktree set handed out where it
        may fail)."""
        _outside(clone, "back", name="box")
        real = seat.mail._worktree_config
        monkeypatch.setattr(seat.mail, "_worktree_config", lambda root, **kw: (
            (None, "git exited 128") if Path(root) == clone else real(root, **kw)))
        with pytest.raises(seat.Undecided) as caught:
            seat.resolve(clone, "box")
        said = str(caught.value)
        assert "the operator's call" in said and "per-worktree config is on could not be read" in said, said
        assert "git -C" not in said, said

    def test_the_list_on_a_clone_that_names_none_drops_a_dormant_copy(self, seat, clone):
        """On a clone that names no machine, a dormant copy outside the folder
        answers no name and writes nothing, as on a named clone; and a main
        checkout's own ``--worktree`` name is not called "not its clone's"
        where the clone has none. Dies to: the drop kept to a named clone, and
        the words written for one."""
        dormant, named = _outside(clone, "dormant"), _outside(clone, "named", name="box-n")
        _git(clone, "config", "--unset", "espalier.machine")
        _git(clone, "config", "--worktree", "espalier.machine", "solo")
        found, _note = seat.seats(clone, fetch=False, sessions=[])
        paths = {s.path: s for s in found}
        assert str(dormant) not in paths and paths[str(named)].name == "box-n", paths
        text = seat.render(found, "")
        assert "seat solo (a --worktree name set in the main checkout; its clone names none) -- the clone" in text, text
        assert "not its clone's" not in text, text


class TestLaunch:
    def test_an_occupied_seat_is_refused_and_a_gone_session_is_not_occupancy(self, seat, clone, registry, no_claude,
                                                                             capsys):
        """The pack's red. Dies to: dropping the cwd comparison from the
        liveness oracle (launch then proceeds into an occupied checkout)."""
        feat = _worktree(clone, "feat", name="box-feat")
        pid = registry(feat / "src")
        with pytest.raises(seat.Refused) as refused:
            seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=True)
        said = str(refused.value)
        assert said.startswith(f"seat box-feat is occupied: pid {pid} (cli, started 2026-10-15 06:30Z) (their "
                               f"entries are under {registry.dir / 'sessions'}) is in {feat}")
        assert "One checkout holds one session at a time" in said and "Core Rule" not in said
        (registry.dir / "sessions" / f"{pid}.json").unlink()
        registry(feat, pid=_dead_pid())
        assert seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=True) == 0
        assert "claude" in capsys.readouterr().out
        assert no_claude == []

    def test_a_session_in_another_seat_does_not_occupy_this_one(self, seat, clone, registry, capsys):
        feat = _worktree(clone, "feat", name="box-feat")
        registry(clone)
        assert seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=True) == 0
        with pytest.raises(seat.Refused):
            seat.cmd_launch(clone, "box", [], maintenance=False, unchecked=False, print_only=True)
        assert feat.is_dir()

    def test_occupancy_nobody_can_tell_refuses_unless_unchecked(self, seat, clone, monkeypatch, capsys):
        _worktree(clone, "feat", name="box-feat")
        monkeypatch.setattr(seat.sync, "claude_config_dirs", lambda: [clone.parent / "no-such-config"])
        with pytest.raises(seat.Refused) as refused:
            seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=True)
        assert "cannot be told" in str(refused.value) and "--unchecked launches anyway" in str(refused.value)
        assert seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=True, print_only=True) == 0

    def test_a_missing_seat_is_created_from_origin_named_and_given_its_include_files(self, seat, clone, registry,
                                                                                     no_claude, monkeypatch, capsys):
        monkeypatch.setenv("ESPALIER_MAINTENANCE_MODE", "1")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent")
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
        rc = seat.cmd_launch(clone, "box-new", ["--model", "x"], maintenance=False, unchecked=False, print_only=False)
        assert rc == 0
        path = clone / ".claude" / "worktrees" / "new"
        assert _out(path, "rev-parse", "--abbrev-ref", "HEAD") == "worktree-new"
        assert _out(path, "rev-parse", "HEAD") == _out(clone, "rev-parse", "origin/main")
        assert _out(path, "config", "--worktree", "--get", "espalier.machine") == "box-new"
        assert (path / ".claude" / "settings.json").read_bytes() == b'{"hooks": {}}\n'
        (call,) = no_claude
        # The own-clear mod rides first; the operator's arguments pass through
        # unchanged; the first message rides last.
        mod = _mod(seat)
        assert call["argv"][:3 + len(mod)] == ["/fake/bin/claude", *mod, "--model", "x"] and Path(call["cwd"]) == path
        assert call["argv"][3 + len(mod):] == ["--", seat.compose_brief(clone, "box-new", path).text]
        env = call["env"]
        assert "ESPALIER_MAINTENANCE_MODE" not in env and "CLAUDE_CODE_SESSION_ID" not in env
        assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"
        out = capsys.readouterr().out
        assert "created " in out and "copied .claude/settings.json" in out and "named this worktree box-new" in out

    def test_maintenance_is_set_only_when_asked_and_the_seats_venv_leads_the_path(self, seat, clone, registry,
                                                                                  no_claude):
        feat = _worktree(clone, "feat", name="box-feat")
        bindir = feat / ".venv" / ("Scripts" if os.name == "nt" else "bin")
        bindir.mkdir(parents=True)
        seat.cmd_launch(clone, "box-feat", [], maintenance=True, unchecked=False, print_only=False)
        env = no_claude[0]["env"]
        assert env["ESPALIER_MAINTENANCE_MODE"] == "1"
        assert env["PATH"].split(os.pathsep)[0] == str(bindir)

    def test_the_drivers_flags_after_the_seat_are_its_own_and_claudes_follow_the_dashes(self, seat, clone, registry,
                                                                                        no_claude, monkeypatch,
                                                                                        capsys):
        """Dies to: a remainder argument, which took `--print` for claude and
        launched a session (driven 2026-10-15, before this was split)."""
        monkeypatch.chdir(clone)
        assert seat.main(["launch", "box", "--print", "--", "--model", "o p"]) == 0
        assert no_claude == []
        # The first message spans two lines inside its quotes; claude's line is its first:
        # the one holding `claude` as a word. A bare substring took the "own-clear mod
        # loaded from <MOD_DIR>" notice on any checkout under .claude/worktrees/ (#351).
        out = next(line for line in capsys.readouterr().out.splitlines() if " claude " in line)
        assert "'o p'" in out and "You are seat box" in out
        assert seat.split_claude_args(["launch", "x", "--", "--print"]) == (["launch", "x"], ["--print"])

    def test_names_that_are_no_seat_are_refused(self, seat, clone, tmp_path):
        with pytest.raises(seat.Refused, match="no seat 'nobody' here: this clone is 'box'"):
            seat.resolve(clone, "nobody")
        stray = clone / ".claude" / "worktrees" / "stray"
        stray.mkdir(parents=True)
        with pytest.raises(seat.Refused, match="exists but git does not register it as a worktree: look at what is"):
            seat.resolve(clone, "box-stray")
        _worktree(clone, "other", name="box-renamed")
        with pytest.raises(seat.Refused, match=r"is a registered worktree that answers 'box-renamed', not 'box-other'"
                                               r".*launch box-renamed"):
            seat.resolve(clone, "box-other")
        _git(clone, "config", "--unset", "espalier.machine")
        with pytest.raises(seat.Refused, match="this clone names no machine"):
            seat.resolve(clone, "box")

    def test_the_command_line_is_quoted_for_each_shell(self, seat, tmp_path):
        target = seat.Target("box-x", tmp_path / "it's here", True, False)
        ps = seat.command_line(target, ["--model", "o p", "a\u2019b"], maintenance=True, shell="powershell")
        assert ps.startswith(f"Set-Location -LiteralPath '{str(tmp_path / 'it')}''s here'; ")
        assert "$env:ESPALIER_MAINTENANCE_MODE = '1'" in ps and ps.endswith("claude '--model' 'o p' 'a\u2019\u2019b'")
        assert "Remove-Item Env:VIRTUAL_ENV" in ps
        plain = seat.command_line(target, [], maintenance=False, shell="powershell")
        assert "Remove-Item Env:ESPALIER_MAINTENANCE_MODE" in plain
        with pytest.raises(seat.Refused, match="Windows PowerShell 5.1 splits"):
            seat.command_line(target, ['say "hi"'], maintenance=False, shell="powershell")
        sh = seat.command_line(target, ["--model", "o p"], maintenance=False, shell="posix")
        assert sh.endswith(f"&& env -u ESPALIER_MAINTENANCE_MODE {_own_clear_unsets(seat)} -u ESPALIER_BOX_LOCK_WAIT_S -u VIRTUAL_ENV claude --model 'o p'")
        bindir = target.path / ".venv" / ("Scripts" if os.name == "nt" else "bin")
        bindir.mkdir(parents=True)
        with_venv = seat.command_line(target, [], maintenance=False, shell="powershell")
        assert f"$env:PATH = '{str(bindir).replace(chr(39), chr(39) * 2)};' + $env:PATH" in with_venv
        posix_venv = seat.command_line(target, [], maintenance=True, shell="posix")
        assert f"env {_own_clear_unsets(seat)} -u ESPALIER_BOX_LOCK_WAIT_S ESPALIER_MAINTENANCE_MODE=1 VIRTUAL_ENV=" in posix_venv and ':"$PATH" claude' in posix_venv

    def test_the_posix_line_puts_every_unset_before_the_first_assignment(self, seat, tmp_path):
        """Driven 2026-10-26 on macOS 25.6: BSD env stops reading options at the
        first assignment, so `env ESPALIER_MAINTENANCE_MODE=1 -u VIRTUAL_ENV ...`
        exits 127 (`env: -u: No such file or directory`); GNU env permutes its
        arguments and takes either order, so a Linux reader never sees it. All
        four combinations (maintenance on or off, a .venv under the target or
        not) are rendered, and in each no option follows the first assignment;
        the one that mixed them in the wrong order is pinned word for word.
        Dies to: the maintenance assignment rendered before the venv unset."""
        target = seat.Target("box-x", tmp_path, True, False)
        sh = seat.command_line(target, [], maintenance=True, shell="posix")
        assert sh.endswith(f"&& env {_own_clear_unsets(seat)} -u ESPALIER_BOX_LOCK_WAIT_S -u VIRTUAL_ENV ESPALIER_MAINTENANCE_MODE=1 claude"), sh
        for venv in (False, True):
            if venv:
                (target.path / ".venv" / ("Scripts" if os.name == "nt" else "bin")).mkdir(parents=True)
            for maintenance in (True, False):
                line = seat.command_line(target, [], maintenance=maintenance, shell="posix")
                words = line.split(" env ", 1)[1].split(" claude", 1)[0].split()
                assignments = [i for i, w in enumerate(words) if "=" in w]
                after = words[assignments[0]:] if assignments else []
                assert not [w for w in after if w.startswith("-")], (venv, maintenance, words)

    def test_the_childs_environment_drops_the_parent_sessions_and_names_the_seats_venv(self, seat, tmp_path):
        """Read 2026-10-15: a session exports its pid, id and messaging token
        to its children, and VIRTUAL_ENV named the main checkout's .venv in a
        worktree seat's session. Dies to: dropping a name, or a prefix strip
        that also drops a user's CLAUDE_CODE_USE_BEDROCK."""
        base = {name: "x" for name in seat.SESSION_ENV | seat.OWN_CLEAR_ENV}
        base.update({"CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CONFIG_DIR": "/cfg", "VIRTUAL_ENV": "/other/.venv",
                     "ESPALIER_MAINTENANCE_MODE": "1", "PATH": "/bin"})
        target = seat.Target("box-x", tmp_path, True, False)
        env = seat.child_env(target, maintenance=False, base=base)
        assert not set(seat.SESSION_ENV) & set(env)
        # The own-clear's names never ride in from the launcher's shell; the
        # flag is set only when the mod rides the launch (the own-clear lane).
        assert not seat.OWN_CLEAR_ENV & set(env)
        assert seat.child_env(target, maintenance=False, base=base, own_clear=True)["ESPALIER_OWN_CLEAR"] == "1"
        assert {"CLAUDECODE", "CLAUDE_CODE_MESSAGING_TOKEN", "AI_AGENT"} <= seat.SESSION_ENV
        assert env["CLAUDE_CODE_USE_BEDROCK"] == "1" and env["CLAUDE_CONFIG_DIR"] == "/cfg"
        assert "VIRTUAL_ENV" not in env and "ESPALIER_MAINTENANCE_MODE" not in env
        bindir = tmp_path / ".venv" / ("Scripts" if os.name == "nt" else "bin")
        bindir.mkdir(parents=True)
        env = seat.child_env(target, maintenance=True, base=base)
        assert env["VIRTUAL_ENV"] == str(tmp_path / ".venv") and env["PATH"].split(os.pathsep)[0] == str(bindir)

    def test_a_seat_never_inherits_a_box_lock_wait_bound(self, seat, tmp_path):
        """DEF-4056: the bound is for one capped run. Exported once in a
        terminal and inherited, it would end every tier the seat ran at it,
        the Stop hook's pytest gate included. Mutation: the name left in the
        environment, or off either printed launch line."""
        target = seat.Target("box-x", tmp_path, True, False)
        assert seat.BOX_LOCK_WAIT_KEY == "ESPALIER_BOX_LOCK_WAIT_S"
        env = seat.child_env(target, maintenance=False, base={"PATH": "/bin", seat.BOX_LOCK_WAIT_KEY: "60"})
        assert seat.BOX_LOCK_WAIT_KEY not in env
        posix = seat.command_line(target, [], maintenance=False, shell="posix")
        assert f"-u {seat.BOX_LOCK_WAIT_KEY}" in posix, posix
        ps = seat.command_line(target, [], maintenance=False, shell="powershell")
        assert f"Remove-Item Env:{seat.BOX_LOCK_WAIT_KEY} -ErrorAction SilentlyContinue" in ps, ps

    def test_from_inside_a_session_nothing_is_created_or_started(self, seat, clone, registry, monkeypatch):
        """Dies to: a launch an AI collaborator types under its Bash tool,
        which would start a hidden child session (the stripped variables keep
        Claude Code from even knowing it is nested)."""
        monkeypatch.setattr(seat, "run_session", lambda *a, **k: pytest.fail("a session was started"))
        monkeypatch.setenv("CLAUDECODE", "1")
        with pytest.raises(seat.Refused, match="runs inside a Claude Code session"):
            seat.cmd_launch(clone, "box-new", [], maintenance=False, unchecked=False, print_only=False)
        assert not (clone / ".claude" / "worktrees" / "new").exists()
        monkeypatch.delenv("CLAUDECODE")
        with pytest.raises(seat.Refused, match="standard input is not a terminal"):
            seat.cmd_launch(clone, "box-new", [], maintenance=False, unchecked=False, print_only=False)

    def test_an_existing_seat_without_its_settings_gets_them_before_it_starts(self, seat, clone, registry,
                                                                              no_claude, capsys):
        """A worktree made by hand, or before .worktreeinclude, or left by a
        failed create. Dies to: copying only on create, so the session starts
        with no hook at all."""
        feat = _worktree(clone, "feat", name="box-feat")
        assert not (feat / ".claude" / "settings.json").exists()
        seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=False)
        assert (feat / ".claude" / "settings.json").read_bytes() == b'{"hooks": {}}\n'
        assert "copied .claude/settings.json from the clone" in capsys.readouterr().out

    def test_include_entries_it_cannot_take_are_said_not_raised(self, seat, clone):
        (clone / ".worktreeinclude").write_bytes(
            b".claude/settings.json\n!negated.txt\n/anchored.json\nconf/\n/nonexistent*\n")
        (clone / "anchored.json").write_bytes(b"{}\n")
        (clone / ".gitignore").write_bytes(b".claude/settings.json\n.claude/worktrees/\nanchored.json\n")
        target = clone / "plain-dir"
        target.mkdir()
        copied, skipped = seat.copy_includes(clone, target)
        assert copied == [".claude/settings.json", "anchored.json"]
        assert [s.split(" ")[0] for s in skipped] == ["!negated.txt", "conf/"]

    def test_a_worktrees_folder_git_does_not_ignore_is_refused_before_anything_is_made(self, seat, clone, registry,
                                                                                       no_claude):
        (clone / ".gitignore").write_bytes(b".claude/settings.json\n")
        with pytest.raises(seat.Refused, match=r"\.claude/worktrees/new/ is not ignored by git here"):
            seat.cmd_launch(clone, "box-new", [], maintenance=False, unchecked=False, print_only=False)
        assert not (clone / ".claude" / "worktrees" / "new").exists()

    def test_a_leftover_merged_branch_is_reused_and_unmerged_work_is_not(self, seat, clone, registry, no_claude,
                                                                        capsys):
        _git(clone, "branch", "worktree-new", "origin/main")
        seat.cmd_launch(clone, "box-new", [], maintenance=False, unchecked=False, print_only=False)
        assert "deleted the leftover branch worktree-new" in capsys.readouterr().out
        _git(clone, "worktree", "remove", "--force", str(clone / ".claude" / "worktrees" / "new"))
        _git(clone, "switch", "--quiet", "worktree-new")
        (clone / "w.txt").write_bytes(b"w\n")
        _git(clone, "add", "w.txt")
        _git(clone, "commit", "--quiet", "-m", "work")
        _git(clone, "switch", "--quiet", "main")
        with pytest.raises(seat.Refused, match="a branch worktree-new already exists with work origin/main lacks"):
            seat.cmd_launch(clone, "box-new", [], maintenance=False, unchecked=False, print_only=False)

    def test_a_session_only_a_marker_names_passes_with_unchecked(self, seat, clone, registry, monkeypatch):
        feat = _worktree(clone, "feat", name="box-feat")
        marker = {"session_id": "m1", "pid": os.getpid(), "cwd": str(feat)}
        monkeypatch.setattr(seat.sync, "_default_marker_reader",
                            lambda: (lambda tree: [marker] if seat.sync._norm(tree) == seat.sync._norm(feat) else []))
        with pytest.raises(seat.Refused, match="only a session marker names it: --unchecked passes it"):
            seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=True)
        assert seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=True, print_only=True) == 0
        registry(feat)
        with pytest.raises(seat.Refused, match="is occupied"):
            seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=True, print_only=True)


# -- brief ---------------------------------------------------------------------------

#: The worker tick as the operator pasted it on 2026-10-15 18:56Z (mail note
#: 215fbb, verbatim), with its review step read from the diff since 2026-10-16
#: (air's assign 0b750e, on the operator's yes), and since 2026-10-24 the two
#: sentences the operator approved on the channel (the ack on the call
#: 20261024T065923Z-air-b366a4): TP-702 3-A's refresh sentence after the lane
#: step, and TP-703e 1-C-2's proceed clause in place of the STOP clause, as
#: amended by that lane's failure-mode review to the protocol paragraph as it
#: stood on 2026-10-24 ("an open goal call" read as "an open operator call" on
#: the seat's own fork, since TP-703d moved the calls to the board; the
#: request's age read from the board's asks line; a redirect: ack re-aims; a
#: row is never a stop; the shelved: note names the job the push closed, the
#: push having released the claims; a shelved lane is not re-fixed each tick;
#: the refresh command spelled like the tick's other commands, with no bare
#: interpreter); and since 2026-10-30 the STOP sends one request opening with
#: stopped: (DEF-5030, the fix shape the seat named under the ruling d6ef5a
#: that minted the row: a stopped worker sent nothing, so the board showed no
#: stopped seat); and since 2026-11-09 the STOP names the parked job's assign
#: id and says the dispatcher's release, ack and re-send (DEF-3038, the shape
#: the dispatcher approved on 20261107T060117Z-air-5e86f5 (C)). The self-host render must reproduce it byte for byte; its 15
#: minutes is DISPATCHER_TICK's interval, rendered, never copied. Since
#: 2026-11-15 (the operator's ruling, assign 20261115T064945Z-air-6c9da9) the
#: loop line is /loop 10m /worker-tick and the tick is what the command has
#: seat.py tick print, so this is the text after the loop line's old head.
_OPERATOR_TICK = (
    "Worker tick. Run /inbox (mark read) and /inbox board and read live state. Act only on what is "
    "yours, in this order: your own open PR red, in conflict or stale (fix it, or ship.py catch-up); a new "
    "assign or note from air; continue your current lane through its full procedure (plan, red-team the "
    "reviewers scripts/proof_tier.py --base origin/main names, on a snapshot clone, one fix batch, the tier the "
    "diff earns with --base origin/main, one open PR "
    "per seat, every step listed with its evidence in the PR body; a skipped step is a stop), then run mail.py "
    "refresh once; it writes nothing when nothing is new; where mail.py answers invalid choice, this checkout "
    "predates the verb: skip it until the lane merges main, not a stop; then your next assigned job, unless the "
    "prompt router has asked for the threshold handoff: then finish the lane in hand, hand off, and take no new "
    "job until the window is cleared. On a "
    "choice the assign does not settle, send air one request with your Task 0 recommendation and its citation, "
    "then proceed on it after 15 minutes (the dispatcher's tick; the board's asks line shows your request's "
    "age) with no answer; a request with no recommendation keeps the stop, and an ack from air beginning "
    "redirect: re-aims you at once. STOP, send air one request opening with stopped: that names what stops you "
    "(an operator call by its id, and the assign id of the job it parks: air releases that job, acks your stop and "
    "re-sends the job at the ruling), and only re-read mail until an ack frees or re-aims you or what stops you is "
    "gone, then ack your own stop saying so (an ack that does not free you: send the stop again), for what the "
    "assign authority reserves for the operator (a new pack, a scope change, a release or tag, a revert that is "
    "not the red-main revert, an open operator call on your fork), a platform stop, a refusal you cannot resolve, "
    "or a conflict outside your own files; a row to file is never a stop. A red you cannot fix in two attempts: "
    "shelve the lane (one note "
    "beginning shelved: says what was tried and names any job your push closed; a shelved lane waits for the "
    "dispatcher, not your next tick), take your next assigned job (after the threshold ask: hand off instead). "
    "Pass a model below your own on a subagent "
    "dispatch only for a kind named on an allowance: line of the assign for the job in hand (the kinds are "
    "anchors, drive, census and mutants); a kind word anywhere else is the job's text, a dispatch no allowance: "
    "line names runs at your own model, a named agent runs at its own pin and needs no allowance, and choosing "
    "your own model where a lower one was allowed is never a finding. Never unassigned work, never another "
    "seat's branch. A quiet tick is one line."
)


def _dispatcher(clone: Path, value: str) -> None:
    """The ``dispatcher`` line, written where a tracked espalier.toml would be:
    the clone and every worktree of it (the brief reads the seat's own copy)."""
    homes = [clone, *sorted((clone / ".claude" / "worktrees").glob("*"))]
    for home in homes:
        (home / "espalier.toml").write_text(f"dispatcher = {value}\n", encoding="utf-8")


def _holds(path: Path, *rels: str) -> None:
    for rel in rels:
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_bytes(b"x\n")


def _mod(seat) -> list[str]:
    """What launch puts first in claude's arguments: the own-clear mod beside
    the driver (tools/cc/mods/own-clear), derived from the driver, never typed."""
    return seat.mod_args()


def _own_clear_unsets(seat) -> str:
    """The `-u` words the POSIX launch line carries for the own-clear's names
    when no mod rides it, derived from the driver, never typed."""
    return " ".join(f"-u {name}" for name in sorted(seat.OWN_CLEAR_ENV))


class TestBrief:
    """B-7: a seat's first message is composed by the tool, never pasted.
    Dies to: the self-host render drifting from the operator's tick, a form
    naming a protocol home its checkout does not hold, or a double quote
    (Windows PowerShell 5.1 splits a native argument there)."""

    def test_a_worker_on_this_repository_gets_the_operators_tick_verbatim(self, seat, clone):
        _dispatcher(clone, '"air"')
        feat = _worktree(clone, "feat", name="box-feat")
        _holds(feat, "memory/parallel-work-protocol.md", "docs/WORKFLOW.md", "scripts/proof_tier.py")
        brief = seat.compose_brief(clone, "box-feat", feat)
        first, loop = brief.text.split("\n")
        assert brief.role == "worker" and loop == brief.loop == seat.WORKER_TICK == "/loop 10m /worker-tick"
        assert brief.tick == _OPERATOR_TICK and brief.tick not in brief.text
        assert first.startswith("You are seat box-feat, a worker under the dispatcher air (Core Rule 15, "
                                "memory/parallel-work-protocol.md). Orient from the banner, then run /inbox")
        assert first.endswith("Then start the worker loop on the next line with no further message from the operator.")

    def test_an_adopter_worker_is_pointed_at_what_its_checkout_holds(self, seat, clone):
        _dispatcher(clone, '"hub"')
        feat = _worktree(clone, "feat", name="box-feat")
        _holds(feat, "docs/WORKFLOW.md")
        seeded = seat.compose_brief(clone, "box-feat", feat)
        assert "a worker under the dispatcher hub (docs/WORKFLOW.md, Parallel seats)." in seeded.text
        assert "the proof the change earns per /implement-task step 7" in seeded.tick and "--base" not in seeded.text
        assert ("the reviewers the diff earns, dispatched at once with your edits frozen, per "
                "/implement-task step 6") in seeded.tick
        assert "snapshot clone" not in seeded.text   # defined on this repository only
        assert "note from hub;" in seeded.tick and "send hub one request" in seeded.tick
        assert "memory/" not in seeded.text and "Core Rule" not in seeded.text
        # The dispatch-model sentence is this repository's (its dispatcher assigns on its own);
        # an adopter's dispatcher proposes every assign. Read on the RENDERED adopter loop, so a
        # move of the sentence into the shared tick template cannot carry it here unseen.
        assert "allowance:" not in seeded.text and "below your own" not in seeded.text
        bare = seat.compose_brief(clone, "box-feat", clone / "no-such-checkout")   # the clone holds neither
        assert "(the /inbox command's body)" in bare.text

    def test_with_no_dispatcher_named_a_worker_answers_to_the_operator(self, seat, clone):
        brief = seat.compose_brief(clone, "box", clone)
        assert brief.role == "worker"
        assert "a worker under the operator (espalier.toml names no dispatcher)" in brief.text
        assert "note from the operator;" in brief.tick and "send the operator one request" in brief.tick

    def test_the_red_duty_names_the_fix_forward_ruling_beside_the_revert(self, seat, clone):
        """After the dispatcher ruled a red base a fix-forward, its own brief's
        red duty still read `revert first on a red main` and nothing else, so
        the standing duty contradicted the ruling it had just given (the
        failure-mode review of the ruling lane). The duty names the ruling
        beside the revert, which stays the default, and points at the gridlock
        sentence below it, which names the head and the flag; an adopter's
        duty is unchanged (it proposes the revert and carries no gridlock
        sentence). Dies to: the duty offering the revert alone."""
        _dispatcher(clone, '"box"')
        _holds(clone, "memory/parallel-work-protocol.md")
        first = seat.compose_brief(clone, "box", clone).text.split("\n")[0]
        duty = "revert first on a red main, or where no revert clears it rule a fix-forward by run id and lane (below)"
        assert duty in first and first.index(duty) < first.index(seat.SELF_HOST_GRIDLOCK)
        assert "gridlock: fix forward run <the red post-merge run's id>" in first[first.index(duty):]
        assert "fix-forward" not in seat.ADOPTER_RED and "fix forward" not in seat.ADOPTER_RED

    def test_the_dispatcher_seat_gets_the_board_loop_and_its_duties(self, seat, clone):
        _dispatcher(clone, '"box"')
        _holds(clone, "memory/parallel-work-protocol.md")
        brief = seat.compose_brief(clone, "box", clone)
        first, loop = brief.text.split("\n")
        assert brief.role == "dispatcher" and loop == brief.loop == "/loop 15m /dispatcher-tick"
        assert first.startswith("You are the dispatcher seat box (Core Rule 15, memory/parallel-work-protocol.md). "
                                "Orient from the banner, then run /inbox (mark read) and /inbox board.")
        assert "revert first on a red main" in first and "Decisions stay the operator's." in first
        # The model is the operator's launch setting, never the template's: no flag and no model
        # name in the brief. The word itself may appear (the allowance clause names what a
        # subagent may run below, 2026-10-25).
        import re
        assert re.search(r"--model|\b(opus|sonnet|haiku|fable)\b", first, re.IGNORECASE) is None, first
        _holds(clone, "cc/GOAL.md")
        assert "Orient from the banner and cc/GOAL.md's notes, then" in seat.compose_brief(clone, "box", clone).text

    def test_the_self_host_dispatcher_is_sent_to_the_channel_for_the_operators_open_calls(self, seat, clone):
        """TP-703d sub-task 4: the open calls ride the mail channel as
        `OPERATOR CALL:` requests the board lists for every seat, not a
        gitignored goal file one checkout reads. Dies to: the brief still
        naming cc/GOAL.md as their home."""
        _dispatcher(clone, '"box"')
        _holds(clone, "memory/parallel-work-protocol.md")
        first = seat.compose_brief(clone, "box", clone).text.split("\n")[0]
        assert "OPERATOR CALL:" in first and "asks" in first, first
        assert "open calls in cc/GOAL.md" not in first and "cc/GOAL.md" not in seat.SELF_HOST_ASSIGN

    def test_both_briefs_name_the_handoff_that_writes_the_seats_row(self, seat, clone):
        """A seat's first message named the reads, the jobs and the loop and
        never the handoff that writes its Session Log row. Dies to: either
        clause dropped, or moved past the last sentence the endswith pin reads."""
        _dispatcher(clone, '"air"')
        feat = _worktree(clone, "feat", name="box-feat")
        _holds(feat, "memory/parallel-work-protocol.md")
        worker = seat.compose_brief(clone, "box-feat", feat).text.split("\n")[0]
        assert ("When the operator ends your session, or when the prompt router's threshold ask says to (a lane "
                "in hand finishes through its own landing first; the ask never ships a half-done lane), run "
                "/handoff: it writes your Session Log row and ships it on your open lane or parks it; after a "
                "threshold handoff take no new job until the window is cleared. Then start the worker loop") in worker, worker
        _dispatcher(clone, '"box"')
        _holds(clone, "memory/parallel-work-protocol.md")
        dispatcher = seat.compose_brief(clone, "box", clone).text.split("\n")[0]
        assert ("Decisions stay the operator's. " + seat.SELF_HOST_GRIDLOCK + "At the operator's word, or when the "
                "prompt router's threshold ask says to (a lane in hand finishes through its own landing first), run "
                "/handoff; it writes your row, derived from the mail and the merges; after a threshold handoff take "
                "no new job until the window is cleared (a red main's revert is not a new job). Start the loop") in dispatcher, dispatcher

    def test_this_repositorys_dispatcher_resolves_a_gridlock_and_an_adopters_brief_is_unchanged(self, seat, clone):
        """The operator's standing rule (2026-10-30): a gridlock -- no seat can
        advance its assigned job and the next step is a decision -- is resolved
        by the dispatcher seat, which rules, acts and reports the ruling as an
        ack (or as a note where no request waits on the ruling), instead of
        filing an operator call and waiting; the operator can
        reverse it. It names this repository's operator, so it rides the
        self-host slot right after 'Decisions stay the operator's.' and an
        adopter's brief is what it was. The sentence is held to its homes by
        its two lists (the gridlock shapes, and what stays the operator's):
        the protocol's Assign authority paragraph and dispatcher row, and Core
        Rule 15, each read with its line wrapping collapsed. Dies to: the
        sentence rendered for every tree, left out of this repository's,
        rendered twice, placed anywhere but after the operator's sentence, or
        either list drifting between the brief and any of the three homes."""
        _dispatcher(clone, '"box"')
        _holds(clone, "docs/WORKFLOW.md")
        adopter = seat.compose_brief(clone, "box", clone).text
        assert "gridlock" not in adopter, adopter
        assert "merged PR bodies. Decisions stay the operator's. At the operator's word" in adopter
        _holds(clone, "memory/parallel-work-protocol.md")
        own = seat.compose_brief(clone, "box", clone).text
        assert ("Decisions stay the operator's. A gridlock, where no seat can advance its assigned job and the "
                "next step is a decision (a red main no revert clears, two lanes in conflict, a ruling a worker "
                "waits on past the hour), is yours to resolve, the one exception to what you propose to the "
                "operator: rule, act and report the ruling as an ack whose text opens with gridlock: (its first "
                "word, so a message opening with RULING or an address is not counted and a seat's name goes after "
                "it; one ruling per message) and carries the facts you read, or as a note opening the same way "
                "where no request waits on the ruling, "
                "instead of filing an operator call and waiting (scripts/seat_day_census.py counts the rulings "
                "by that opening and your row names them); the operator can reverse it, and a new pack, a scope "
                "change, a release or tag stay the operator's. A (stopped) row on the asks line past the hour is "
                "that read: answer it with the ack that frees or re-aims the seat. A red main no revert clears is "
                "ruled the same way, always by an ack (where no request waits on it, --ack names the held seat's "
                "last message): the ack's text opens with the fixed head gridlock: fix forward run <the red "
                "post-merge run's id> and its --lane names the fix lane (a renamed lane gets a second ack); the "
                "seat lands it with python tools/cc/ship.py open --base-red-ruled <that ack's full id> (handoff "
                "takes the same flag), and the revert stays the default. At the operator's word") in own, own
        assert own.count(seat.SELF_HOST_GRIDLOCK) == 1, own
        shapes = "a red main no revert clears, two lanes in conflict, a ruling a worker waits on past the hour"
        kept = "a new pack, a scope change, a release or tag stay the operator's"
        assert shapes in seat.SELF_HOST_GRIDLOCK and kept in seat.SELF_HOST_GRIDLOCK
        prose_shapes = shapes.replace("red main", "red `main`")
        root = Path(__file__).resolve().parents[1]
        protocol = (root / "memory" / "parallel-work-protocol.md").read_text(encoding="utf-8")
        start = protocol.index("**Assign authority")
        paragraph = " ".join(protocol[start:protocol.index("\n\n", start)].split())
        assert "a gridlock is the dispatcher's to resolve" in paragraph and "SELF_HOST_GRIDLOCK" in paragraph
        assert prose_shapes in paragraph and kept in paragraph, paragraph
        assert "the operator can reverse it" in paragraph, paragraph
        assert "falsifies this: a gridlock ruling the operator reverses" in paragraph, paragraph
        row = next((line for line in protocol.splitlines() if line.startswith("| Resolves a gridlock")), "")
        assert prose_shapes in row and "the operator can reverse it" in row, row
        rule = next(line for line in (root / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
                    if line.startswith("15. **Parallel work"))
        assert "is resolved by the dispatcher seat" in rule and kept in rule, rule

    def test_a_stop_is_a_request_opening_with_the_marker_the_board_counts(self, seat):
        """DEF-5030 (2026-10-30): a worker that stopped sent nothing (the
        self-host STOP clause said only re-read mail; the adopter's sent a
        plain request the board could not tell from a question), so the
        board showed no stopped seat for the dispatcher's past-the-hour
        gridlock read. Both clauses send one request opening with
        ``stopped:``, the word's one home ``tools/cc/mail.py::STOPPED_PREFIX``
        beside the operator call's, which the board's asks line counts apart
        and the census table carries; the record homes carry the same word:
        the protocol's seat's-side paragraph and the dispatcher's first-read
        paragraph, the inbox body's asks bullet and the workflow guide's.
        Dies to: a clause that stops without the send, the marker spelled
        apart from the constant in a clause or the census table, or a record
        home that names the stop without the word."""
        root = Path(__file__).resolve().parents[1]
        marker = seat.mail.STOPPED_PREFIX
        assert marker == "stopped:"
        # The resume rule (the failure-mode review): a release or the ruling on an operator
        # call names no stop, so the seat acks its own stop when the cause is gone, and an
        # interim ack that frees nothing is answered by sending the stop again.
        assert (f"STOP, send {{dispatcher}} one request opening with {marker} that names what stops you (an operator "
                "call by its id, and the assign id of the job it parks: {dispatcher} releases that job, acks your "
                "stop and re-sends the job at the ruling), and only re-read mail until an ack frees or re-aims you or "
                "what stops you is gone, "
                "then ack your own stop saying so (an ack that does not free you: send the stop again), for what the "
                "assign authority reserves for the operator") in seat.SELF_HOST_PROCEED
        assert (f"STOP and send {{dispatcher}} one request opening with {marker}, then only re-read mail until it is "
                "answered, on anything not green") in seat.ADOPTER_PROCEED
        # The dispatcher's side: the stop row past the hour is the gridlock read.
        assert ("A (stopped) row on the asks line past the hour is that read: answer it with the ack that frees or "
                "re-aims the seat") in seat.SELF_HOST_GRIDLOCK
        census_path = root / "scripts" / "seat_day_census.py"
        if not census_path.is_file():  # pragma: no cover - adopter tree
            pytest.skip("scripts/seat_day_census.py is self-host dev tooling")
        spec = importlib.util.spec_from_file_location("census_for_the_stop", census_path)
        census = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = census
        spec.loader.exec_module(census)
        assert census.MARKERS["stopped"] == marker
        protocol = " ".join((root / "memory" / "parallel-work-protocol.md").read_text(encoding="utf-8").split())
        assert f"one `request` whose text opens with `{marker}`" in protocol, "the seat's-side paragraph"
        assert "the seat acks its own stop when what stopped it is gone" in protocol, "the resume rule"
        assert f"a request opening with `{marker}`" in protocol, "the dispatcher's first-read paragraph"
        for rel in (".claude/commands/inbox.md", "docs/WORKFLOW.md"):
            body = " ".join((root / rel).read_text(encoding="utf-8").split())
            assert f"A request whose text opens with `{marker}` is a worker's stop" in body, rel
        inbox = " ".join((root / ".claude" / "commands" / "inbox.md").read_text(encoding="utf-8").split())
        assert "a `(stopped)` row past the hour on the `asks:` line is the gridlock's read" in inbox

    def test_the_gridlock_ruling_opens_with_the_marker_the_census_counts(self, seat):
        """DEF-5029 (2026-10-30): the ruling's ack opens with ``gridlock:``, a
        marker in the family of OPERATOR CALL:, redirect:, shelved: and stopped:, and
        scripts/seat_day_census.py counts a ruling by that opening alone and
        names its id on the dispatcher's row (the first two rulings under the
        rule were plain acks no reader counted; a word read anywhere in a text
        counts the briefs' and the assigns' own quotations of it). The word
        has one home, the census's MARKERS table, and the brief's sentences
        are held to it: the dispatcher's ruling clause and the worker tick's
        redirect: and shelved: clauses. Its record homes carry the same word:
        the protocol's Assign authority paragraph and dispatcher row, Core
        Rule 15 and the inbox body's ruling paragraph. A gridlock no request
        waits on may be ruled by a note opening the same way (DEF-4060,
        2026-10-31: note 20261031T105813Z-air-c80653 was a ruling the census
        left out), and each home says so in one phrase; the fix-forward ruling
        is always an ack, since the ship driver reads its lane from an ack
        alone, and the brief and the inbox body say so. Dies to: the brief
        saying the ack carries the facts with no marker, the marker spelled
        apart from the table in any clause, a record home that names the
        ruling without the word, a home that leaves the note out, or the note
        offered for a fix-forward."""
        root = Path(__file__).resolve().parents[1]
        census_path = root / "scripts" / "seat_day_census.py"
        if not census_path.is_file():  # pragma: no cover - adopter tree
            pytest.skip("scripts/seat_day_census.py is self-host dev tooling")
        spec = importlib.util.spec_from_file_location("census_for_the_brief", census_path)
        census = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = census
        spec.loader.exec_module(census)
        marker = census.MARKERS["gridlock"]
        assert marker == "gridlock:"
        note = "a note opening the same way where no request waits on the ruling"
        assert (f"rule, act and report the ruling as an ack whose text opens with {marker} (its first word, so a "
                "message opening with RULING or an address is not counted and a seat's name goes after it; one "
                f"ruling per message) and carries the facts you read, or as {note}, instead "
                "of filing an operator call and waiting (scripts/seat_day_census.py counts the rulings by that "
                "opening and your row names them); the operator can reverse it") in seat.SELF_HOST_GRIDLOCK
        assert "A red main no revert clears is ruled the same way, always by an ack" in seat.SELF_HOST_GRIDLOCK
        assert f"an ack from {{dispatcher}} beginning {census.MARKERS['redirect']} re-aims" in seat.SELF_HOST_PROCEED
        assert f"one note beginning {census.MARKERS['shelved']} says" in seat.SELF_HOST_PROCEED
        protocol = (root / "memory" / "parallel-work-protocol.md").read_text(encoding="utf-8")
        start = protocol.index("**Assign authority")
        paragraph = " ".join(protocol[start:protocol.index("\n\n", start)].split())
        assert f"The ruling's `ack` opens with `{marker}`" in paragraph and note in paragraph, paragraph
        assert "names each ruling's id" in paragraph, paragraph
        row = next((line for line in protocol.splitlines() if line.startswith("| Resolves a gridlock")), "")
        assert f"an `ack` opening with `{marker}`" in row and note in row, row
        rule = next(line for line in (root / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
                    if line.startswith("15. **Parallel work"))
        assert f"as an ack opening with `{marker}`" in rule and note in rule, rule
        raw = (root / ".claude" / "commands" / "inbox.md").read_text(encoding="utf-8")
        inbox = " ".join(raw.split())
        assert f"whose text opens with `{marker}`" in inbox and note in inbox
        assert "seat-day census counts a ruling by that opening on the dispatcher's acks and notes alone" in inbox
        assert f'--text "{marker} <the ruling, the facts you read>"' in inbox
        assert f'send --type note --text "{marker} <the ruling, the facts you read>"' in inbox
        assert "A ruling that fixes a red base forward is always an ack" in inbox
        # The rule renders on this repository alone (the brief's slot is empty elsewhere), so the
        # inbox body says it inside a self-host block that the asset deploy strips.
        from espalier.surface_hygiene import strip_self_host_blocks
        stripped = strip_self_host_blocks(raw, source=".claude/commands/inbox.md")
        assert marker not in stripped and "Core Rule 15" not in stripped

    def test_on_an_adopter_checkout_the_handoff_clauses_name_the_row_alone(self, seat, clone):
        """The push onto the lane and the row derived by the seat census are this
        repository's (`handoff_push`, scripts/seat_day_census.py), so an adopter's
        briefs say only what its /handoff does: write the row. Dies to: either
        self-host phrase pasted into the template instead of its slot."""
        _dispatcher(clone, '"hub"')
        feat = _worktree(clone, "feat", name="box-feat")
        _holds(feat, "docs/WORKFLOW.md")
        worker = seat.compose_brief(clone, "box-feat", feat).text.split("\n")[0]
        assert ("run /handoff: it writes your Session Log row; after a threshold handoff take no new job until "
                "the window is cleared. Then start the worker loop") in worker, worker
        assert "parks it" not in worker, worker
        _dispatcher(clone, '"box"')
        dispatcher = seat.compose_brief(clone, "box", clone).text.split("\n")[0]
        assert ("run /handoff; it writes your row; after a threshold handoff take no new job until the window "
                "is cleared (a red main's revert is not a new job). Start the loop") in dispatcher, dispatcher
        assert "derived from" not in dispatcher, dispatcher

    def test_every_sentence_that_names_the_threshold_ask_names_the_lane_in_hand_rule(self, seat):
        """The rule that a threshold handoff never ships a half-done lane lives
        in prose, in the briefs and the tick; a sentence that names the ask
        without the lane-in-hand exception reopens the push the ask was built
        to avoid (the failure-mode review, 2026-10-26)."""
        import re
        for name in ("WORKER_BRIEF", "DISPATCHER_BRIEF", "WORKER_TICK_PROMPT", "SELF_HOST_PROCEED"):
            text = getattr(seat, name)
            for sentence in re.split(r"(?<=[.;])\s", text):
                # The ask sentences; "after a threshold handoff ..." is the post-handoff rule.
                if "threshold ask" in sentence or "asked for the threshold handoff" in sentence:
                    assert ("lane in hand" in sentence or "hand off instead" in sentence), (name, sentence)

    def test_an_unusable_dispatcher_setting_refuses_the_brief_and_launch_names_the_way_past(self, seat, clone,
                                                                                            registry, no_claude):
        _dispatcher(clone, '"Not A Name"')   # not lowercase letters, digits and hyphens
        with pytest.raises(seat.Refused, match="the brief names the dispatcher, and "):
            seat.compose_brief(clone, "box", clone)
        _worktree(clone, "feat", name="box-feat")
        with pytest.raises(seat.Refused, match="--no-brief launches without the first message"):
            seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=False)
        with pytest.raises(seat.Refused, match="the brief names the dispatcher"):   # before the worktree is made
            seat.cmd_launch(clone, "box-new", [], maintenance=False, unchecked=False, print_only=False)
        assert not (clone / ".claude" / "worktrees" / "new").exists()
        assert seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=False,
                               brief=False) == 0
        assert no_claude[-1]["argv"] == ["/fake/bin/claude", *_mod(seat)]

    def test_every_form_is_ascii_with_no_double_quote_and_survives_both_shells(self, seat, clone, tmp_path):
        _dispatcher(clone, '"air"')
        feat = _worktree(clone, "feat", name="box-feat")
        worker = seat.compose_brief(clone, "box-feat", clone)
        _holds(feat, "memory/parallel-work-protocol.md", "scripts/proof_tier.py")
        self_host = seat.compose_brief(clone, "box-feat", feat)
        _dispatcher(clone, '"box"')
        _holds(clone, "cc/GOAL.md")
        dispatcher = seat.compose_brief(clone, "box", clone)
        target = seat.Target("box-feat", feat, True, False)
        for brief in (worker, self_host, dispatcher):
            assert brief.text.isascii() and '"' not in brief.text and "%" not in brief.text, brief.text
            assert not set(brief.text) & set(seat._PS_DOUBLE)
            # The tick the loop's command prints keeps the same alphabet: it once rode this argument whole.
            assert brief.tick.isascii() and '"' not in brief.tick and "%" not in brief.tick, brief.tick
            # Every seat's loop runs a command whose verb prints a tick (the dispatcher's since job 5154dc).
            assert brief.tick, brief.role
            # Both --print forms quote it whole, so it reaches claude as one argument.
            assert seat.command_line(target, [brief.text], maintenance=False, shell="powershell")
            line = seat.command_line(target, [brief.text], maintenance=False, shell="posix")
            assert seat.shlex.split(line.split(" claude ", 1)[1]) == [brief.text]

    def test_launch_passes_the_brief_last_and_no_brief_drops_it(self, seat, clone, registry, no_claude, monkeypatch,
                                                                capsys):
        _dispatcher(clone, '"air"')
        feat = _worktree(clone, "feat", name="box-feat")
        monkeypatch.chdir(clone)
        assert seat.main(["launch", "box-feat", "--", "--model", "x"]) == 0
        assert no_claude[-1]["argv"] == ["/fake/bin/claude", *_mod(seat), "--model", "x", "--",
                                         seat.compose_brief(clone, "box-feat", feat).text]
        assert seat.main(["launch", "box-feat", "--no-brief", "--", "--model", "x"]) == 0
        assert no_claude[-1]["argv"] == ["/fake/bin/claude", *_mod(seat), "--model", "x"]
        assert "no first message" in capsys.readouterr().out
        assert seat.main(["brief", "box-feat"]) == 0
        assert capsys.readouterr().out == seat.compose_brief(clone, "box-feat", feat).text + "\n"

    def test_launch_loads_the_own_clear_mod_first_and_no_mod_drops_it(self, seat, clone, registry, no_claude,
                                                                      monkeypatch, capsys):
        """The own-clear lane (2026-10-26): the mod beside the driver rides
        first in claude's arguments, before the operator's own and the brief's
        `--`; `--no-mod` leaves it out and says so; the print form carries it.
        Dies to: the flag after the brief's `--` (read as the prompt), a launch
        that loads the mod silently, or a print line without it."""
        _dispatcher(clone, '"air"')
        _worktree(clone, "feat", name="box-feat")
        monkeypatch.chdir(clone)
        assert seat.mod_args() == ["--plugin-dir", str(seat.MOD_DIR)]   # this repository ships it
        monkeypatch.setenv("ESPALIER_OWN_CLEAR_ROOT", "/elsewhere")   # a root left exported: never inherited
        assert seat.main(["launch", "box-feat", "--", "--model", "x"]) == 0
        argv = no_claude[-1]["argv"]
        assert argv[:3] == ["/fake/bin/claude", "--plugin-dir", str(seat.MOD_DIR)]
        assert argv.index("--") > argv.index("--plugin-dir")
        env = no_claude[-1]["env"]
        assert env["ESPALIER_OWN_CLEAR"] == "1" and "ESPALIER_OWN_CLEAR_ROOT" not in env
        assert "own-clear mod loaded" in capsys.readouterr().out
        assert seat.main(["launch", "box-feat", "--no-mod", "--", "--model", "x"]) == 0
        assert "--plugin-dir" not in no_claude[-1]["argv"]
        assert "ESPALIER_OWN_CLEAR" not in no_claude[-1]["env"]
        assert "no own-clear mod" in capsys.readouterr().out
        assert seat.main(["launch", "box-feat", "--print", "--shell", "posix"]) == 0
        line = capsys.readouterr().out
        # The spelling the shell reads: shlex quotes a path with a backslash (a Windows
        # seat's D:\...) or a space, and leaves a plain POSIX path bare.
        assert f"--plugin-dir {seat.shlex.quote(str(seat.MOD_DIR))}" in line and "ESPALIER_OWN_CLEAR=1" in line
        assert seat.main(["launch", "box-feat", "--no-mod", "--print", "--shell", "posix"]) == 0
        line = capsys.readouterr().out
        assert "--plugin-dir" not in line and "-u ESPALIER_OWN_CLEAR " in line

    def test_an_adopters_dispatcher_proposes_the_revert_and_this_repository_reverts_first(self, seat, clone):
        """Reverting first on a red base is this repository's rule; an
        adopter's dispatcher loop must not do it unasked. Dies to: the
        self-host duty rendered for every tree."""
        _dispatcher(clone, '"box"')
        _holds(clone, "docs/WORKFLOW.md")
        adopter = seat.compose_brief(clone, "box", clone).text
        assert "propose the revert to the operator on a red main" in adopter and "revert first" not in adopter
        _holds(clone, "memory/parallel-work-protocol.md")
        assert "revert first on a red main" in seat.compose_brief(clone, "box", clone).text

    def test_this_repositorys_dispatcher_assigns_and_an_adopters_proposes(self, seat, clone):
        """The operator's assign-authority decision (2026-10-15) is this
        repository's; an adopter's dispatcher proposes every assign, as before.
        Dies to: the self-host authority rendered for every tree, or the
        self-host brief still asking for a yes per assign."""
        _dispatcher(clone, '"box"')
        _holds(clone, "docs/WORKFLOW.md")
        adopter = seat.compose_brief(clone, "box", clone).text
        assert "propose assigns and releases to the operator and send them on a yes" in adopter
        assert "on your own" not in adopter
        _holds(clone, "memory/parallel-work-protocol.md")
        own = seat.compose_brief(clone, "box", clone).text
        assert "within approved packs and live ledger rows on your own" in own
        assert "Assign authority paragraph" in own and "send them on a yes" not in own
        # TP-703e 1-D: the assign's shape rides the self-host brief and never the adopter's.
        assert "each assign in its shape" in own and "under 900 characters" in own
        assert "in its shape" not in adopter

    def test_this_repositorys_dispatcher_keeps_the_report_rules_and_an_adopters_brief_is_unchanged(self, seat, clone):
        """The operator's rules for a dispatcher's report (2026-10-20): counts
        name their population, a tool's setting is quoted from the tool, the
        day's figures come from the census. They name a script only this
        repository holds, so they ride the self-host slot and an adopter's
        brief is what it was, byte for byte. Dies to: the sentence rendered
        for every tree, or left out of this repository's."""
        _dispatcher(clone, '"box"')
        _holds(clone, "docs/WORKFLOW.md")
        adopter = seat.compose_brief(clone, "box", clone).text
        assert "seat_day_census" not in adopter and "names its population" not in adopter
        # Up to the operator's sentence only: the gridlock slot and the handoff clause sit after it.
        assert "merged PR bodies. Decisions stay the operator's." in adopter
        _holds(clone, "memory/parallel-work-protocol.md")
        own = seat.compose_brief(clone, "box", clone).text
        assert ("merged PR bodies. " + seat.SELF_HOST_FIGURES + "Decisions stay the operator's.") in own
        assert "the day's figures come from scripts/seat_day_census.py, never carried by hand." in own

    def test_the_seats_wait_in_the_protocol_is_the_dispatchers_tick_interval(self, seat):
        """The seat proceeds on its Task 0 recommendation after the dispatcher's
        tick interval with no answer (the protocol's "The seat's side of it", the
        operator's yes of 2026-10-19). Dies to: the loop's interval moved and the
        paragraph left saying the old number."""
        import re
        minutes = re.search(r"/loop (\d+)m", seat.DISPATCHER_TICK).group(1)
        text = (Path(__file__).resolve().parents[1] / "memory" / "parallel-work-protocol.md").read_text(encoding="utf-8")
        start = text.index("**The seat's side of it**")
        paragraph = text[start:text.index("\n\n", start)]
        assert f"{minutes} minutes" in paragraph and "DISPATCHER_TICK" in paragraph
        # the worker-seat section quotes the dispatcher's loop line whole
        assert f"`{seat.DISPATCHER_TICK}`" in text

    def test_the_dispatch_model_kinds_in_the_tick_are_the_protocols(self, seat, clone):
        """The allowance kinds have one source, DISPATCH_KINDS, rendered into the
        self-host tick and the dispatcher brief, and the protocol's "The model
        on a dispatch" paragraph defines each as a backticked word in the same
        order (the operator's rule, 2026-10-25). The lists are compared to each
        other, never to a copy here. Dies to: a kind renamed or added in one
        place and not the other, a kinds field left unrendered in either brief,
        the allowance: marker dropped from the tick, or the sentence rendered
        into the adopter form, whose dispatcher proposes every assign."""
        import re
        kinds = seat.DISPATCH_KINDS
        assert len(kinds) >= 2 and len(set(kinds)) == len(kinds), kinds
        phrase = seat.dispatch_kinds_phrase()
        assert phrase.startswith(kinds[0]) and phrase.endswith(f" and {kinds[-1]}")
        assert "(the kinds are {kinds})" in seat.SELF_HOST_PROCEED and "(the kinds are {kinds})" in seat.SELF_HOST_ASSIGN
        text = (Path(__file__).resolve().parents[1] / "memory" / "parallel-work-protocol.md").read_text(encoding="utf-8")
        start = text.index("**The model on a dispatch")
        paragraph = text[start:text.index("\n\n", start)]
        assert re.findall(r"`([a-z]+)`\s+\(", paragraph) == list(kinds), paragraph   # the note wraps at 80
        assert "`allowance:`" in paragraph and "DISPATCH_KINDS" in paragraph
        _dispatcher(clone, '"air"')
        feat = _worktree(clone, "feat", name="box-feat")
        _holds(feat, "memory/parallel-work-protocol.md", "scripts/proof_tier.py")
        loop = seat.compose_brief(clone, "box-feat", feat).tick
        assert f"(the kinds are {phrase})" in loop and "named on an allowance: line" in loop and "{" not in loop
        _holds(clone, "memory/parallel-work-protocol.md")   # the dispatcher's own checkout picks its form
        dispatcher = seat.compose_brief(clone, "air", clone).text
        assert f"(the kinds are {phrase})" in dispatcher and "an allowance: line" in dispatcher and "{" not in dispatcher
        assert "a model below" not in seat.ADOPTER_PROCEED and "{kinds}" not in seat.ADOPTER_PROCEED

    def test_the_ticks_wait_is_the_dispatchers_tick_interval_rendered_never_copied(self, seat, clone):
        """The proceed clause waits the dispatcher's tick interval (TP-703e 1-C-2,
        in the tick on the operator's yes of 2026-10-24), and the dispatcher
        brief quotes the same interval, so both numbers come from
        DISPATCHER_TICK at render. Dies to: a literal number typed into either
        template, which the next change to DISPATCHER_TICK would leave behind,
        or the clause dropped from the self-host tick."""
        import re
        minutes = re.search(r"/loop (\d+)m", seat.DISPATCHER_TICK).group(1)
        assert seat.TICK_MINUTES == minutes
        assert "proceed on it after {wait} minutes (the dispatcher's tick" in seat.SELF_HOST_PROCEED
        assert "read the board every {every} minutes" in seat.DISPATCHER_BRIEF
        for template in (seat.WORKER_TICK_PROMPT, seat.SELF_HOST_PROCEED, seat.ADOPTER_PROCEED, seat.DISPATCHER_BRIEF):
            assert re.search(r"\d+ minutes", template) is None, template
        _dispatcher(clone, '"air"')
        feat = _worktree(clone, "feat", name="box-feat")
        _holds(feat, "memory/parallel-work-protocol.md", "scripts/proof_tier.py")
        loop = seat.compose_brief(clone, "box-feat", feat).tick
        assert f"proceed on it after {minutes} minutes (the dispatcher's tick" in loop
        assert "run mail.py refresh once" in loop and "{" not in loop
        dispatcher = seat.compose_brief(clone, "air", clone).text
        assert f"read the board every {minutes} minutes" in dispatcher and "{" not in dispatcher

    def test_each_loop_interval_divides_the_hour(self, seat):
        """/handoff step 5b re-creates a seat's loop as cron `*/N * * * *` for
        `/loop Nm`, the spelling /loop itself used for both live loops on
        2026-11-14. That cron runs every N minutes only when N divides 60
        (`*/7` fires at :56 and again at :00), so this pins each loop line's
        interval to a divisor of the hour below 60 (`*/60` is no interval).
        Dies to: a tick changed to an interval that does not divide it, which
        the step would re-create as a loop with an uneven gap."""
        import re
        for loop in (seat.WORKER_TICK, seat.DISPATCHER_TICK):
            match = re.match(r"/loop (\d+)m ", loop)
            assert match, loop[:40]
            minutes = int(match.group(1))
            assert minutes < 60 and 60 % minutes == 0, match.group(0)

    def test_an_adopters_worker_keeps_the_stop_and_ask_form(self, seat, clone):
        """The proceed authority is this repository's operator's decision (the
        protocol's "The seat's side of it"); an adopter's dispatcher proposes
        every assign, so its seat stops and asks, as the tick did before
        2026-10-24, and still refreshes its claim. Dies to: the proceed clause
        rendered on a tree whose protocol home is the seeded workflow guide,
        where no Task 0, assign authority or dispatcher tick is defined."""
        _dispatcher(clone, '"ops"')
        feat = _worktree(clone, "feat", name="box-feat")
        _holds(feat, "docs/WORKFLOW.md")
        loop = seat.compose_brief(clone, "box-feat", feat).tick
        assert ("STOP and send ops one request opening with stopped:, then only re-read mail until it is answered, on "
                "anything not green") in loop
        assert "proceed on it" not in loop and "Task 0" not in loop and "shelve" not in loop
        assert "run mail.py refresh once" in loop and "{" not in loop
        assert loop.isascii() and '"' not in loop and "%" not in loop

    def test_this_repositorys_worker_runs_the_reviewers_its_diff_earns(self, seat, clone):
        """The self-host tick names the review line the tier script prints, at
        the base the tier uses; the adopter's points at step 6's rule. Dies to:
        either tick saying both reviewers for every lane (the 1.8 then 2.6
        review rounds per reviewed pull request the assign measured)."""
        _dispatcher(clone, '"air"')
        feat = _worktree(clone, "feat", name="box-feat")
        _holds(feat, "docs/WORKFLOW.md")
        assert "the reviewers the diff earns" in seat.compose_brief(clone, "box-feat", feat).tick
        _holds(feat, "memory/parallel-work-protocol.md")
        # the protocol alone: no script to print the line, so step 6's rule
        assert "the reviewers the diff earns" in seat.compose_brief(clone, "box-feat", feat).tick
        _holds(feat, "scripts/proof_tier.py")
        loop = seat.compose_brief(clone, "box-feat", feat).tick
        assert "red-team the reviewers scripts/proof_tier.py --base origin/main names" in loop
        assert "both reviewers" not in loop

    @pytest.mark.contract   # it reads a shipped command body (tests/test_marker_taxonomy.py)
    def test_the_adopter_phrases_name_steps_the_shipped_command_body_holds(self, seat):
        """The adopter tick points at /implement-task's steps by number: a
        step inserted into the shipped body would re-point every adopter
        seat. Dies to: a renumbered body with the phrases left behind."""
        body = (REPO_ROOT / "espalier" / "assets" / "claude" / "commands" / "implement-task.md").read_text(
            encoding="utf-8")
        steps = body.splitlines()
        assert seat.ADOPTER_REVIEW.endswith("per /implement-task step 6")
        assert any(s.startswith("6. **Review before the one full run.") for s in steps)
        assert any(s.startswith("7. **Run the proof tier once") for s in steps)

    @pytest.mark.parametrize("args", [["-p"], ["--print"], ["--resume"], ["--resume=abc"], ["-c"], ["--continue"],
                                      ["--teleport"], ["fix this"], ["--model", "x", "--", "fix this"]])
    def test_the_brief_is_refused_beside_a_mode_flag_or_a_prompt_of_its_own(self, seat, clone, registry, no_claude,
                                                                           args):
        """Dies to: passing the brief beside them (two prompts, or a resumed
        session that never reads it)."""
        _worktree(clone, "feat", name="box-feat")
        with pytest.raises(seat.Refused, match="--no-brief launches without the first message"):
            seat.cmd_launch(clone, "box-feat", args, maintenance=False, unchecked=False, print_only=False)
        assert no_claude == []
        assert seat.cmd_launch(clone, "box-feat", args, maintenance=False, unchecked=False, print_only=False,
                               brief=False) == 0
        assert no_claude[-1]["argv"] == ["/fake/bin/claude", *_mod(seat), *args]

    def test_a_list_option_keeps_its_values_and_the_brief_follows_a_dashdash(self, seat, clone, registry, no_claude):
        """Driven on 2.1.301: a prompt after `--add-dir <dir>` was read as a
        second directory and the session had no prompt; after a `--` it was
        answered. Dies to: the brief appended bare."""
        feat = _worktree(clone, "feat", name="box-feat")
        args = ["--add-dir", "a", "b"]
        assert seat.cmd_launch(clone, "box-feat", args, maintenance=False, unchecked=False, print_only=False) == 0
        assert no_claude[-1]["argv"] == ["/fake/bin/claude", *_mod(seat), *args, "--",
                                         seat.compose_brief(clone, "box-feat", feat).text]

    def test_a_cmd_shim_refuses_the_brief_because_cmd_cuts_it_at_its_line_break(self, seat, clone, registry,
                                                                                no_claude, monkeypatch):
        """Driven by the failure-mode review on this host: a .cmd given the
        two-line brief received only its first line, so the loop never
        arrived. Dies to: launching through the shim with the brief."""
        _worktree(clone, "feat", name="box-feat")
        real = seat.shutil.which
        monkeypatch.setattr(seat.shutil, "which", lambda name, path=None:
                            "C:/npm/claude.CMD" if name == "claude" else real(name, path=path))
        for print_only in (False, True):
            with pytest.raises(seat.Refused, match="a script cmd.exe runs, which cuts an argument at its line break"):
                seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=print_only)
        assert seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=False,
                               brief=False) == 0

    def test_the_banner_line_is_the_short_form_of_the_same_brief(self, seat, clone):
        """Its interval is read from the loop each form ends with, so the two
        cannot drift. Dies to: an interval spelled apart from the template."""
        _dispatcher(clone, '"box"')
        worker = seat.compose_brief(clone, "box-feat", None)
        dispatcher = seat.compose_brief(clone, "box", None)
        assert seat.brief_line(worker.role, "box-feat", "py -3") == (
            "run /inbox, then /inbox board, then start the worker loop (/loop 10m); "
            "py -3 tools/cc/seat.py brief box-feat prints the first message")
        assert worker.loop.startswith("/loop 10m ")
        assert seat.brief_line(dispatcher.role, "box") == (
            "run /inbox, then /inbox board, then start the board loop (/loop 15m)")
        assert dispatcher.loop.startswith("/loop 15m ")

    def test_the_banner_line_invites_no_second_loop_where_the_window_kept_its_own(self, seat, clone):
        """DEF-4052: a seat's interval loop is a session-only job that lives
        as long as the process, so a /clear and a compaction keep it, and the
        line that still said "then start the worker loop" after the own-clear
        invited a second one beside it (measured on win, 2026-11-02, with the
        running loop listed). A start and a resume, a new process, keep the
        invitation. Dies to: the source ignored, or the invitation kept on a
        clear or a compaction."""
        _dispatcher(clone, '"box"')
        for role, seat_name, what, every in (("worker", "box-feat", "worker", "10m"), ("dispatcher", "box", "board", "15m")):
            for source in ("startup", "resume", ""):
                assert seat.brief_line(role, seat_name, "py -3", source=source).startswith(
                    f"run /inbox, then /inbox board, then start the {what} loop (/loop {every}); "), (role, source)
            for source, said in (("clear", "a /clear"), ("compact", "a compaction")):
                line = seat.brief_line(role, seat_name, "py -3", source=source)
                assert line == (f"run /inbox, then /inbox board; the {what} loop (/loop {every}) survives {said}: "
                                f"where CronList lists it, start no second one; py -3 tools/cc/seat.py brief "
                                f"{seat_name} prints the first message"), line
                assert "then start" not in line and line.isascii() and '"' not in line


# -- the worker tick command ---------------------------------------------------------

class TestTheWorkerTickCommand:
    """A worker seat's loop line names a command, and the command's body has
    the driver print the seat's tick, composed from the checkout at each
    tick, so no window carries or copies the tick's text (the operator's
    ruling of 2026-11-15). Dies to: a loop line that carries the tick itself,
    a line naming a command no body holds, a tick verb that prints another
    checkout's tick, or one that prints a worker's tick for the dispatcher."""

    @pytest.mark.contract   # it reads a shipped command body (tests/test_marker_taxonomy.py)
    def test_the_worker_loop_line_names_a_command_the_tree_holds(self, seat):
        loop = seat.WORKER_TICK
        assert loop.startswith("/loop 10m "), loop[:40]
        command = loop.split(" ", 2)[2]
        assert command.startswith("/") and " " not in command, (
            f"the worker loop line carries its prompt ({len(command)} characters) instead of naming a command")
        body = REPO_ROOT / ".claude" / "commands" / f"{command[1:]}.md"
        assert body.is_file(), body
        assert "python tools/cc/seat.py tick" in body.read_text(encoding="utf-8")

    def test_the_tick_verb_prints_this_checkouts_seat_tick(self, seat, clone, monkeypatch, capsys):
        _dispatcher(clone, '"air"')
        feat = _worktree(clone, "feat", name="box-feat")
        _holds(feat, "memory/parallel-work-protocol.md", "docs/WORKFLOW.md", "scripts/proof_tier.py")
        monkeypatch.chdir(feat)
        assert seat.main(["tick"]) == 0
        out = capsys.readouterr().out
        assert out == seat.compose_brief(clone, "box-feat", feat).tick + "\n" == _OPERATOR_TICK + "\n"
        monkeypatch.chdir(clone)   # a seat named: its own checkout composes it, as brief does
        assert seat.main(["tick", "box-feat"]) == 0
        assert capsys.readouterr().out == out

    def test_the_tick_verb_refuses_the_dispatcher_and_a_checkout_with_no_seat_name(self, seat, clone, monkeypatch,
                                                                                capsys):
        """The worker tick is refused on the dispatcher seat, so /worker-tick in
        a window answering the dispatcher's name takes no dispatcher actions
        (the role guard air's ruling 20261116T170600Z-air-204f5b kept)."""
        _dispatcher(clone, '"box"')
        monkeypatch.chdir(clone)
        assert seat.main(["tick"]) == 1
        err = capsys.readouterr().err
        assert "box is the dispatcher seat" in err and seat.DISPATCHER_TICK in err, err
        _git(clone, "config", "--unset", "espalier.machine")
        assert seat.main(["tick"]) == 1
        err = capsys.readouterr().err
        assert "answers no seat name" in err and "git config espalier.machine is not set" in err, err

    def test_a_worktree_with_no_name_of_its_own_is_refused_as_nameless_never_as_the_dispatcher(
            self, seat, clone, monkeypatch, capsys):
        """A worker worktree that lost its own name answers its clone's, and
        under a clone that is the dispatcher the verb once refused it as the
        dispatcher, whose refusal the command body ends the tick on, so the
        seat skipped even the reduced tick at every fire (the failure-mode
        review, 2026-11-15, driven). Dies to: the unscoped name read."""
        _dispatcher(clone, '"box"')
        feat = _worktree(clone, "feat")   # no name of its own; the clone's is box, the dispatcher
        monkeypatch.chdir(feat)
        assert seat.main(["tick"]) == 1
        err = capsys.readouterr().err
        assert "answers no seat name" in err and "no name of its own" in err and "dispatcher" not in err, err

    def test_the_tick_opens_with_the_head_an_older_loop_is_found_by(self, seat, clone):
        """A loop started before the worker's line named its command carries
        the tick itself, and CronList shows its head (this string, read from
        air-work's loop listing on 2026-11-15); /handoff step 5b finds such a
        loop by that head being a prefix of what the tick verb prints. Dies
        to: the tick's opening reworded while such loops still run, which
        leaves them unmatched until Claude Code deletes them at seven days.
        Drop this pin seven days after the last handoff that could see one."""
        head = "Worker tick. Run /inbox (mark read) and /inbox board and read live state. Act o"
        _dispatcher(clone, '"air"')
        feat = _worktree(clone, "feat", name="box-feat")
        assert seat.compose_brief(clone, "box-feat", feat).tick.startswith(head)   # the seeded form
        _holds(feat, "memory/parallel-work-protocol.md", "scripts/proof_tier.py")
        assert seat.compose_brief(clone, "box-feat", feat).tick.startswith(head)   # this repository's


# -- the dispatcher tick command -----------------------------------------------------

#: The board tick the dispatcher's loop has run since 2026-11-16 (cron 3ec21fd2,
#: in place of the /inbox board loop after the operator's context review, note
#: 20261116T063413Z-air-1ea850 (1)), read verbatim from air's ack
#: 20261116T164900Z-air-09d526, with the house's interpreter spelling (python,
#: where the cron's read python3; air's ruling 20261116T170600Z-air-204f5b). The
#: dispatcher's loop line is /loop 15m /dispatcher-tick since job
#: 20261116T105110Z-air-5154dc, and this is what the command has seat.py tick
#: --role dispatcher print on this repository for the seat air on the base main.
#: A change to it is the operator's decision.
_OPERATOR_BOARD_TICK = (
    "Board tick (dispatcher seat air). Run `python tools/cc/board.py` and act on what it shows under your "
    "dispatcher duties: answer worker asks within the hour, keep each worker at two live jobs, revert a red main "
    "first, or where no revert clears it, rule a fix-forward by run id, and send OPERATOR CALL: requests for the "
    "operator's decisions. Read .claude/commands/inbox.md Step 2c "
    "only for a board line you cannot read. Reply in a few lines; where nothing needs action, say so in one line."
)


class TestTheDispatcherTickCommand:
    """The dispatcher's loop line names a command too, whose body has the
    driver print the board tick, composed from the checkout at each tick (job
    20261116T105110Z-air-5154dc, item (1) of the operator's note
    20261116T063413Z-air-1ea850): the loop named /inbox board, whose whole
    body went in at every fire (13,114 tokens a tick, the median of 34), and
    the lean prompt that replaced it lived in one session's cron alone. Dies
    to: a loop line naming a command no body holds or one that is not the
    dispatcher's own, a tick verb that refuses the dispatcher, or one board
    tick for this repository and an adopter's tree."""

    @pytest.mark.contract   # it reads a shipped command body (tests/test_marker_taxonomy.py)
    def test_the_board_loop_line_names_the_dispatchers_own_command_the_tree_holds(self, seat):
        loop = seat.DISPATCHER_TICK
        assert loop.startswith("/loop 15m "), loop[:40]
        command = loop.split(" ", 2)[2]
        assert command == getattr(seat, "DISPATCHER_COMMAND", None), (
            f"the board loop line runs {command!r}, not the dispatcher's own command")
        body = REPO_ROOT / ".claude" / "commands" / f"{command[1:]}.md"
        assert body.is_file(), body
        assert "python tools/cc/seat.py tick --role dispatcher" in body.read_text(encoding="utf-8")

    @pytest.mark.contract   # it reads shipped command bodies (tests/test_marker_taxonomy.py)
    @pytest.mark.parametrize("role", ["worker", "dispatcher"])
    def test_each_roles_command_body_runs_the_tick_verb_for_its_role_alone(self, seat, role):
        """The whole line each body runs, per role from ``TICK_ROLES``: a
        substring pin on the worker's body was met by the dispatcher's line
        too (the failure-mode review's 5). The worker's body names no
        ``--role`` and takes the verb's default, which a driver older than the
        flag also answers (the code review's 1). Dies to: either body running
        the other's tick, or a default that is not the worker's."""
        command, _ = seat.TICK_ROLES[role]
        body = (REPO_ROOT / ".claude" / "commands" / f"{command[1:]}.md").read_text(encoding="utf-8")
        runs = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("python tools/cc/seat.py tick")]
        assert runs == ["python tools/cc/seat.py tick" + ("" if role == "worker" else f" --role {role}")], runs
        assert seat.build_parser().parse_args(["tick"]).role == "worker"

    @pytest.mark.contract   # it reads a shipped command body (tests/test_marker_taxonomy.py)
    def test_the_board_ticks_inbox_step_is_a_heading_the_body_holds(self, seat):
        """The board tick sends a reader who cannot read a board line to one
        step of the inbox body. Dies to: that body renumbered or retitled
        under the tick, leaving its pointer at nothing (the failure-mode
        review's 2)."""
        import re
        step = re.search(r"\.claude/commands/inbox\.md (Step \w+)", seat.DISPATCHER_TICK_PROMPT)
        assert step, seat.DISPATCHER_TICK_PROMPT
        body = (REPO_ROOT / ".claude" / "commands" / "inbox.md").read_text(encoding="utf-8")
        assert f"\n## {step.group(1)}: Board\n" in body, step.group(1)

    def test_the_tick_verb_prints_the_dispatchers_board_tick(self, seat, clone, monkeypatch, capsys):
        """Asked for the dispatcher's role, the verb prints the board tick,
        which renders on this repository to the prompt the operator approved
        (note 1ea850), the house's interpreter spelling apart."""
        _dispatcher(clone, '"air"')
        _git(clone, "config", "espalier.machine", "air")
        _holds(clone, "memory/parallel-work-protocol.md")
        monkeypatch.chdir(clone)
        code = seat.main(["tick", "--role", "dispatcher"])
        out, err = capsys.readouterr()
        assert code == 0, err
        assert out == seat.compose_brief(clone, "air", clone).tick + "\n" == _OPERATOR_BOARD_TICK + "\n"
        assert seat.main(["tick", "air", "--role", "dispatcher"]) == 0   # a seat named: its checkout composes it
        assert capsys.readouterr().out == out

    def test_the_board_tick_is_refused_on_a_worker_seat(self, seat, clone, monkeypatch, capsys):
        """The role guard's other side: /dispatcher-tick in a worker's window
        takes no dispatcher actions. Dies to: a verb that prints whatever tick
        the seat's role has, whichever command asked."""
        _dispatcher(clone, '"air"')
        monkeypatch.chdir(clone)   # the clone answers box, a worker under air
        assert seat.main(["tick", "--role", "dispatcher"]) == 1
        err = capsys.readouterr().err
        assert "box is a worker seat" in err and seat.WORKER_TICK in err and "no board tick" in err, err

    def test_a_worktree_with_no_name_of_its_own_gets_no_board_tick(self, seat, clone, monkeypatch, capsys):
        """A linked worktree with no name of its own answers its clone's,
        which here is the dispatcher's: asked for the dispatcher's role, it is
        refused as nameless, so /dispatcher-tick's body keeps the tick to the
        board under the window's own first message and the worktree never
        prints the dispatcher's tick as its own (the code review's nit). Dies
        to: the role read from the clone's name before the worktree's."""
        _dispatcher(clone, '"box"')
        feat = _worktree(clone, "feat")   # no name of its own; the clone's is box, the dispatcher
        monkeypatch.chdir(feat)
        assert seat.main(["tick", "--role", "dispatcher"]) == 1
        out, err = capsys.readouterr()
        assert out == "" and "answers no seat name" in err and "no name of its own" in err, (out, err)

    def test_an_adopters_board_tick_proposes_what_this_repositorys_dispatcher_does_itself(self, seat, clone):
        """This repository's dispatcher keeps each worker at two jobs and
        reverts a red base first on its own authority; an adopter's proposes
        assigns, releases and the revert to the operator (ADOPTER_ASSIGN,
        ADOPTER_RED), so its tick says that. Dies to: one board tick for both."""
        _dispatcher(clone, '"box"')
        adopter = seat.compose_brief(clone, "box", clone).tick
        assert adopter.startswith("Board tick (dispatcher seat box). Run `python tools/cc/board.py` "), adopter
        assert "propose" in adopter and "the revert of a red main to the operator" in adopter, adopter
        assert "two live jobs" not in adopter and "OPERATOR CALL:" not in adopter, adopter
        _holds(clone, "memory/parallel-work-protocol.md")
        own = seat.compose_brief(clone, "box", clone).tick
        assert "keep each worker at two live jobs, revert a red main first" in own, own
        for tick in (adopter, own):
            assert tick.isascii() and '"' not in tick and "%" not in tick and "{" not in tick, tick


# -- retire --------------------------------------------------------------------------

class TestRetire:
    def test_a_seats_claims_are_released_under_its_own_name_then_its_worktree_goes(self, seat, clone, registry,
                                                                                    capsys):
        """The pack's red: the protocol's open item 5. Dies to: removing the
        worktree before the release (the claim then stays live with no seat
        left to close it), or sending the release under the clone's name."""
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat", paths=["README.md"])
        _send(seat, feat, "box-feat", "claim", "a row", ids=["DEF-1"])
        assert len(_live_claims_from(seat, clone, "box-feat")) == 2
        assert seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True) == 0
        assert _live_claims_from(seat, clone, "box-feat") == []
        assert not feat.exists() and "lane/feat" not in _out(clone, "branch", "--format=%(refname:short)").split()
        origin_file = _out(clone.parent / "origin.git", "show", "refs/heads/mail/box-feat:mail.jsonl")
        releases = [json.loads(ln) for ln in origin_file.splitlines() if json.loads(ln)["type"] == "release"]
        assert [r["from"] for r in releases] == ["box-feat", "box-feat"]
        out = capsys.readouterr().out
        assert f"retired box-feat: removed {feat}" in out

    def test_an_occupied_seat_is_neither_released_nor_removed(self, seat, clone, registry):
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat")
        registry(feat)
        with pytest.raises(seat.Refused, match="seat box-feat is occupied"):
            seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True)
        assert feat.is_dir() and len(_live_claims_from(seat, clone, "box-feat")) == 1

    def test_a_list_killed_after_a_removal_that_worked_still_retires(self, seat, clone, registry, monkeypatch,
                                                                     capsys):
        """The reaper reads the worktree list back after the removal; that read
        killed at its cap read as the worktree still registered, so retire
        exited 1 with "git did not remove it" over a worktree git had removed
        (the dispatcher's ruling on the killed-read class). Dies to: reading a
        list that did not answer as the worktree still being there."""
        feat = _worktree(clone, "feat", name="box-feat")
        sync, reap, removed = seat.sync, seat.sync.reap_worktrees, []

        def runner(argv, *, cwd, timeout):
            if removed and argv[1:3] == ["worktree", "list"]:
                return None
            return sync.run(argv, cwd=cwd, timeout=timeout)

        def spawner(argv, *, cwd, wait, kill):
            done = sync.spawn(argv, cwd=cwd, wait=wait, kill=kill)
            if argv[1:3] == ["worktree", "remove"]:
                removed.append(argv)
            return done

        monkeypatch.setattr(sync, "reap_worktrees", lambda *a, **k: reap(*a, runner=runner, spawner=spawner, **k))
        assert seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True) == 0
        assert removed and not feat.exists()
        assert f"retired box-feat: removed {feat}" in capsys.readouterr().out

    def test_occupancy_nobody_can_tell_releases_and_removes_nothing(self, seat, clone, monkeypatch):
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat")
        monkeypatch.setattr(seat.sync, "claude_config_dirs", lambda: [clone.parent / "no-such-config"])
        with pytest.raises(seat.Refused, match="cannot be told"):
            seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True)
        assert feat.is_dir() and len(_live_claims_from(seat, clone, "box-feat")) == 1

    def test_a_seat_holding_jobs_is_refused_unless_they_are_handed_back(self, seat, clone, registry, capsys):
        """The dispatcher's job and the seat's claim on ONE lane (the ordinary
        case). Dies to: a release by lane, which closes the job too while the
        driver says it left jobs alone (the failure-mode review drove it)."""
        feat = _worktree(clone, "feat", name="box-feat")
        assign = _send(seat, clone, "box", "assign", "build it", lane="lane/feat", seat="box-feat")
        claim = _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat")
        with pytest.raises(seat.Refused, match=r"seat box-feat holds 1 job\(s\) from the dispatcher \(lane/feat\)"):
            seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True)
        by_machine, _ = seat.mail.read_mail(clone)
        assert [j["id"] for j in seat.mail.live_assignments(by_machine)] == [assign["id"]]
        assert len(_live_claims_from(seat, clone, "box-feat")) == 1 and feat.is_dir()
        assert seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True, return_jobs=True) == 0
        origin_file = _out(clone.parent / "origin.git", "show", "refs/heads/mail/box-feat:mail.jsonl")
        releases = [json.loads(ln) for ln in origin_file.splitlines() if json.loads(ln)["type"] == "release"]
        assert [(r["ack"], r["re"]["lane"]) for r in releases] == [(claim["id"], ""), (assign["id"], "")]
        assert "goes back to the dispatcher" in releases[1]["text"]
        by_machine, _ = seat.mail.read_mail(clone)
        assert seat.mail.live_assignments(by_machine) == [] and not feat.exists()

    def test_a_dispatcher_setting_that_does_not_read_retires_nothing_and_says_so(self, seat, clone, registry):
        """The fold counts no assign under a broken dispatcher setting, so
        retire's own read would see no job to hand back. Dies to: the list
        printing "jobs: none" unqualified, and a retire that releases the
        claim and removes the worktree with the job unseen (DEF-2043's review)."""
        feat = _worktree(clone, "feat", name="box-feat")
        # The clone's copy alone: the setting is read at the clone root, and a
        # copy in the worktree would keep it as an uncommitted change instead.
        (clone / "espalier.toml").write_bytes(b"dispatcher = 7\n")
        _send(seat, clone, "box", "assign", "build it", lane="lane/next", seat="box-feat")
        _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat")
        found, note = seat.seats(clone, fetch=True)
        assert note.startswith("no seat's jobs are counted (espalier.toml sets dispatcher = 7"), note
        removal = {s.name: s for s in found}["box-feat"].removal
        assert removal.startswith("its seat box-feat's jobs could not be read (espalier.toml sets dispatcher = 7"), removal
        assert "; its seat box-feat holds 1 live claim (lane/feat)" in removal, removal
        with pytest.raises(seat.Refused, match=r"would be kept \(its seat box-feat's jobs could not be read"):
            seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True, return_jobs=True)
        assert len(_live_claims_from(seat, clone, "box-feat")) == 1 and feat.is_dir()

    def test_a_worktree_that_must_stay_keeps_its_claims(self, seat, clone, registry):
        """Live claims usually mean unpushed work. Dies to: releasing first and
        judging the removal after, which leaves the work kept and unclaimed."""
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat")
        (feat / "work.txt").write_bytes(b"unpushed\n")
        _git(feat, "add", "work.txt")
        _git(feat, "commit", "--quiet", "-m", "work not on main")
        with pytest.raises(seat.Refused, match=r"would be kept \(1 commit\(s\) not in main \(lane/feat\)\), so "
                                               r"nothing was released"):
            seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True)
        assert len(_live_claims_from(seat, clone, "box-feat")) == 1 and feat.is_dir()

    def test_a_channel_that_cannot_be_read_retires_nothing(self, seat, clone, registry, monkeypatch):
        feat = _worktree(clone, "feat", name="box-feat")

        def unreadable(root, **kw):
            raise seat.mail.Unresolvable("git for-each-ref failed")

        monkeypatch.setattr(seat.mail, "read_mail", unreadable)
        with pytest.raises(seat.Refused, match="the mail channel could not be read .* nothing is released or removed"):
            seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=False)
        assert feat.is_dir()

    def test_a_failed_fetch_at_the_first_read_retires_nothing(self, seat, clone, registry):
        """DEF-4036, the first read: a fetch that failed was a note, and the
        retire went on from the refs as last fetched, so a job the dispatcher
        gave the seat since was never seen and the seat went with the job
        still live. ``--no-fetch`` stays the way to retire on what is here.
        Dies to: the failed fetch read as a note and the retire carried on."""
        feat = _worktree(clone, "feat", name="box-feat")
        job = _send(seat, _other_box(clone, "air"), "air", "assign", "given after the last fetch", ids=["DEF-9"],
                    seat="box-feat")
        origin = _out(clone, "remote", "get-url", "origin")
        _git(clone, "remote", "set-url", "origin", str(clone.parent / "gone.git"))
        with pytest.raises(seat.Refused, match=r"the mail fetch failed \(.*\), so a job given to box-feat since the "
                                               r"last fetch would not be seen: nothing is released or removed"):
            seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True)
        assert feat.is_dir()
        _git(clone, "remote", "set-url", "origin", origin)
        seat.mail.fetch_mail(clone)
        by_machine, _ = seat.mail.read_mail(clone)
        assert [j["id"] for j in seat.mail.live_assignments(by_machine)] == [job["id"]]

    def test_a_failed_fetch_at_the_confirming_read_keeps_the_worktree(self, seat, clone, registry, monkeypatch):
        """DEF-4036, the second read: after its releases retire fetched again
        without reading the answer and confirmed against the refs as last
        fetched, so a job given between the two reads was never seen and the
        worktree went. Dies to: the confirming fetch's answer left unread."""
        feat = _worktree(clone, "feat", name="box-feat")
        claim = _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat")
        air, origin = _other_box(clone, "air"), _out(clone, "remote", "get-url", "origin")
        real, calls, job = seat.mail.fetch_mail, [], {}

        def fetch(root, **kw):
            calls.append(root)
            if len(calls) == 2:   # the confirming read: a job lands on origin, then origin stops answering
                job.update(_send(seat, air, "air", "assign", "given between the reads", ids=["DEF-9"], seat="box-feat"))
                _git(clone, "remote", "set-url", "origin", str(clone.parent / "gone.git"))
            return real(root, **kw)

        monkeypatch.setattr(seat.mail, "fetch_mail", fetch)
        with pytest.raises(seat.Refused, match=r"the releases were sent, and the fetch that confirms them failed "
                                               r"\(.*\): the worktree is kept"):
            seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True)
        assert len(calls) == 2 and feat.is_dir()
        _git(clone, "remote", "set-url", "origin", origin)
        real(clone)
        by_machine, _ = seat.mail.read_mail(clone)
        assert [c["id"] for c in seat.mail.live_claims(by_machine)] == [], claim
        assert [j["id"] for j in seat.mail.live_assignments(by_machine)] == [job["id"]]

    def test_an_unread_channel_at_the_confirming_read_keeps_the_worktree(self, seat, clone, registry, monkeypatch):
        """The sibling of DEF-4036's second read (code review): the confirm
        read the channel after the releases and an unreadable one came back
        empty, which read as nothing left, so the worktree went unconfirmed.
        Dies to: the confirming read's note thrown away."""
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat")
        real_read, real_send, sent, failed = seat.mail.read_mail, seat.mail.send, [], []

        def send(root, message, **kw):
            sent.append(message["type"])
            return real_send(root, message, **kw)

        def read(root, **kw):
            if sent and not failed:   # the first read after a release went out: the confirming one
                failed.append(root)
                raise seat.mail.Unresolvable("git for-each-ref timed out")
            return real_read(root, **kw)

        monkeypatch.setattr(seat.mail, "send", send)
        monkeypatch.setattr(seat.mail, "read_mail", read)
        with pytest.raises(seat.Refused, match=r"the releases were sent, and the mail channel could not be read "
                                               r"\(git for-each-ref timed out\), so they cannot be confirmed: the "
                                               r"worktree is kept"):
            seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True)
        assert sent == ["release"] and len(failed) == 1 and feat.is_dir()

    def test_no_fetch_retires_on_the_refs_here_and_never_fetches(self, seat, clone, registry, monkeypatch):
        """``--no-fetch`` is the explicit way to retire on what is here, at
        both reads. Dies to: the confirming read fetching under it."""
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat")
        calls: list = []
        monkeypatch.setattr(seat.mail, "fetch_mail", lambda root, **kw: calls.append(root) or (False, "not asked"))
        assert seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=False) == 0
        assert calls == [] and not feat.exists()

    def test_an_unread_name_in_the_seat_is_named_as_unread(self, seat, tmp_path, monkeypatch):
        """A name read that failed in the seat's worktree (a timeout, a config
        git cannot parse) was refused as "does not answer the name", which
        sends the operator to rename a seat that may be named. Dies to: the
        unread reason folded into the wrong-name refusal."""
        unread = f"{seat.mail.MACHINE_UNREAD} (git config took longer than 10s), so no machine is named"
        monkeypatch.setattr(seat.mail, "machine_setting", lambda path, **kw: (None, unread))
        with pytest.raises(seat.Refused) as refused:
            seat._send_releases(tmp_path, "box-feat", ["x-1"], "retired")
        said = str(refused.value)
        assert "could not be read" in said and "took longer than 10s" in said, said
        assert "does not answer the name" not in said and "run retire again" in said and said.isascii()
        unset = "git config espalier.machine is not set, so the channel is off (the default)"
        monkeypatch.setattr(seat.mail, "machine_setting", lambda path, **kw: (None, unset))
        with pytest.raises(seat.Refused, match="does not answer the name box-feat"):
            seat._send_releases(tmp_path, "box-feat", ["x-1"], "retired")   # an unset name: no wait helps

    def test_a_dead_holders_lock_is_released_and_said(self, seat, clone, registry, capsys):
        feat = _worktree(clone, "feat", name="box-feat")
        gone = _dead_pid()
        _git(clone, "worktree", "lock", "--reason", f"claude session feat (pid {gone})", str(feat))
        assert seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=False) == 0
        assert f"unlocked feat (pid {gone}): the lock's holder has exited" in capsys.readouterr().out

    def test_a_seat_whose_worktree_is_gone_gets_the_recipe(self, seat, clone, registry):
        gone = _worktree(clone, "gone", name="box-gone")
        lost = _send(seat, gone, "box-gone", "claim", "lost", lane="lane/gone")
        _git(clone, "worktree", "remove", "--force", str(gone))
        with pytest.raises(seat.Refused) as refused:
            seat.cmd_retire(clone, "box-gone", dry_run=False, fetch=True)
        said = str(refused.value)
        assert said.startswith("seat box-gone holds 1 live claim(s) and its worktree is gone")
        assert "git worktree add --detach .claude/worktrees/gone origin/main" in said
        assert "git -C .claude/worktrees/gone config --worktree espalier.machine box-gone" in said
        assert f"python tools/cc/mail.py send --type release --ack {lost['id']}" in said

    def test_the_gone_worktree_recipe_names_only_that_seats_claims(self, seat, clone, registry):
        """Dies to: the recipe built from every live claim on the channel."""
        gone = _worktree(clone, "gone", name="box-gone")
        other = _worktree(clone, "other", name="box-other")
        lost = _send(seat, gone, "box-gone", "claim", "lost", lane="lane/gone")
        theirs = _send(seat, other, "box-other", "claim", "theirs", lane="lane/other")
        _git(clone, "worktree", "remove", "--force", str(gone))
        with pytest.raises(seat.Refused) as refused:
            seat.cmd_retire(clone, "box-gone", dry_run=False, fetch=True)
        said = str(refused.value)
        assert f"--ack {lost['id']}" in said and theirs["id"] not in said, said

    def test_the_gone_worktree_recipe_hands_the_seats_job_back_never_closes_it(self, seat, clone, registry):
        """The recipe releases the seat's claims by their ids. A lane release
        from the seat would read as its lane shipped and close the job it was
        given by its ids (the third closing rule), so the second retire would
        remove the seat with its job closed and never handed back. Dies to:
        the recipe's release by lane."""
        gone = _worktree(clone, "gone", name="box-gone")
        job = _send(seat, clone, "box", "assign", "fix DEF-7", ids=["DEF-7"], seat="box-gone")
        claim = _send(seat, gone, "box-gone", "claim", "DEF-7, started", lane="lane/gone", ids=["DEF-7"])
        _git(clone, "worktree", "remove", "--force", str(gone))
        with pytest.raises(seat.Refused) as refused:
            seat.cmd_retire(clone, "box-gone", dry_run=False, fetch=True)
        recipe = str(refused.value)
        assert f"python tools/cc/mail.py send --type release --ack {claim['id']}" in recipe, recipe
        assert "--lane" not in recipe, recipe
        _git(clone, "worktree", "add", "--detach", str(gone), "origin/main")
        _git(gone, "config", "--worktree", "espalier.machine", "box-gone")
        _send(seat, gone, "box-gone", "release", "", ack=claim["id"])
        seat.mail.fetch_mail(clone)
        by_machine, _ = seat.mail.read_mail(clone)
        assert [j["id"] for j in seat.mail.live_assignments(by_machine, "box")] == [job["id"]]
        with pytest.raises(seat.Refused, match=r"holds 1 job\(s\) from the dispatcher"):
            seat.cmd_retire(clone, "box-gone", dry_run=False, fetch=True)

    def test_the_clone_itself_is_never_retired_and_a_dry_run_changes_nothing(self, seat, clone, registry, capsys):
        with pytest.raises(seat.Refused, match="box is the clone itself"):
            seat.cmd_retire(clone, "box", dry_run=False, fetch=False)
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat")
        seat.cmd_retire(clone, "box-feat", dry_run=True, fetch=True)
        out = capsys.readouterr().out
        assert "dry-run: would release 1 claim(s) of box-feat (lane/feat)" in out
        assert feat.is_dir() and len(_live_claims_from(seat, clone, "box-feat")) == 1



def _kill_reads(seat, monkeypatch, *heads: tuple[str, ...], seen: list | None = None) -> None:
    """Every git the driver builds answers each read whose argv opens with one
    of ``heads`` as one killed at its cap does (no answer), notes every argv in
    ``seen``, and runs the rest."""
    sync = seat.sync
    real = sync._Git

    def runner(argv, *, cwd, timeout):
        if seen is not None:
            seen.append(list(argv))
        if argv[0] == "git" and any(tuple(argv[1:1 + len(h)]) == h for h in heads):
            return None
        return sync.run(argv, cwd=cwd, timeout=timeout)

    class Killing(real):
        def __init__(self, cwd, deadline, _runner=None, spawner=sync.spawn, tally=None):
            super().__init__(cwd, deadline, runner, spawner, tally)

    monkeypatch.setattr(sync, "_Git", Killing)


def _kill_origin_head(seat, monkeypatch, seen: list | None = None) -> None:
    """The `origin/HEAD` read killed; the main fallback behind it still
    answers, which is the guess the driver must not take."""
    _kill_reads(seat, monkeypatch, ("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"), seen=seen)


class TestTheDefaultBranchGitDidNotNameIsNeverGuessed:
    """The driver read origin's default branch as `default_branch(...) or
    "main"`, so a read killed at its cap stood in as `main`: on a clone whose
    default is another branch, a seat built from the wrong base, a brief that
    names it, a recipe that pastes it and a retire that fetches it. Dies to:
    the substitute kept past a read that did not answer."""

    def test_the_helper_tells_a_kill_from_an_answer(self, seat, clone, monkeypatch):
        assert seat.origin_default(seat.sync._Git(clone, None)) == "main"   # control
        _kill_origin_head(seat, monkeypatch)
        assert seat.origin_default(seat.sync._Git(clone, None)) is None

    def test_a_kept_older_checkout_sync_keeps_its_fallback(self, seat, clone):
        """A `checkout_sync.py` from before reads were counted has no
        `unanswered`: the driver keeps the old fallback, never a traceback
        (the failure-mode review drove the AttributeError)."""
        class Older(seat.sync._Git):
            unanswered = None
        assert seat.origin_default(Older(clone, None)) == "main"

    def test_create_refuses_a_base_it_could_not_name(self, seat, clone, monkeypatch):
        _kill_origin_head(seat, monkeypatch)
        target = seat.resolve(clone, "box-new")
        with pytest.raises(seat.Refused, match="git did not answer which branch is origin's default: retry"):
            seat.create(clone, target)
        assert not target.path.exists()

    def test_the_brief_is_refused_rather_than_name_a_guessed_base(self, seat, clone, monkeypatch):
        _dispatcher(clone, '"air"')
        feat = _worktree(clone, "feat", name="box-feat")
        assert seat.compose_brief(clone, "box-feat", feat).role == "worker"   # control
        _kill_origin_head(seat, monkeypatch)
        with pytest.raises(seat.Refused, match="the brief names the base branch, and git did not answer"):
            seat.compose_brief(clone, "box-feat", feat)

    def test_the_by_hand_recipe_names_the_ref_git_resolves_never_main(self, seat, clone, monkeypatch):
        assert "origin/main, then" in seat.by_hand_release(clone, "box", "box-gone", ["c1"])   # control
        _kill_origin_head(seat, monkeypatch)
        text = seat.by_hand_release(clone, "box", "box-gone", ["c1"])
        assert "git worktree add --detach .claude/worktrees/gone origin/HEAD, then" in text, text
        assert "origin/main" not in text

    def test_retire_refuses_rather_than_fetch_a_guessed_base(self, seat, clone, registry, monkeypatch):
        feat = _worktree(clone, "feat", name="box-feat")
        seen: list = []
        _kill_origin_head(seat, monkeypatch, seen)
        with pytest.raises(seat.Refused, match="seat box-feat was not retired: git did not answer"):
            seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True)
        assert feat.is_dir() and not [a for a in seen if "fetch" in a], "no fetch of a guessed base"


class TestTheCreateReadsThatDidNotAnswer:
    """The reads `create` makes past the base: a killed ignore check read as
    "not ignored" (the wrong fix named), a killed worktree list as a branch
    checked out nowhere, and a `branch -D` git never answered as deleted.
    Dies to: any of the three read as an answer."""

    def test_a_killed_ignore_check_is_said_as_a_kill(self, seat, clone, monkeypatch):
        target = seat.resolve(clone, "box-new")
        _kill_reads(seat, monkeypatch, ("check-ignore",))
        with pytest.raises(seat.Refused, match="git did not answer whether .claude/worktrees/new/ is ignored here"):
            seat.create(clone, target)
        assert not target.path.exists()

    def test_a_killed_worktree_list_holds_the_leftover_branch(self, seat, clone, monkeypatch):
        _git(clone, "branch", "worktree-new")
        target = seat.resolve(clone, "box-new")
        _kill_reads(seat, monkeypatch, ("worktree", "list"))
        with pytest.raises(seat.Refused, match="git did not answer which checkouts hold the leftover branch "
                                                "worktree-new"):
            seat.create(clone, target)
        assert "worktree-new" in _out(clone, "branch", "--format=%(refname:short)").split()

    def test_a_branch_delete_git_did_not_answer_is_never_said_deleted(self, seat, clone, monkeypatch, capsys):
        _git(clone, "branch", "worktree-new")
        target = seat.resolve(clone, "box-new")
        _kill_reads(seat, monkeypatch, ("branch", "-D"))
        with pytest.raises(seat.Refused, match="the leftover branch worktree-new .* was not deleted: git did not "
                                                "answer in time"):
            seat.create(clone, target)
        assert "deleted the leftover branch" not in capsys.readouterr().out

    def test_an_include_git_did_not_judge_is_skipped_and_said(self, seat, clone, monkeypatch):
        first, second = clone.parent / "first", clone.parent / "second"
        first.mkdir()
        second.mkdir()
        assert seat.copy_includes(clone, first) == ([".claude/settings.json"], [])   # control
        _kill_reads(seat, monkeypatch, ("check-ignore",))
        assert seat.copy_includes(clone, second) == (
            [], [".claude/settings.json (git did not answer whether it is ignored)"])


class TestTheLauncherSetsTheBoxLock:
    """A seat launched by the tool, or by its printed line, runs under the box
    lock: ``ESPALIER_BOX_LOCK`` names one path per user under the home
    directory unless the parent already named one, so two seats on one box
    take the same lock and CI, which never runs the launcher, never sees it.
    Mutations: the key dropped from the child's environment; an inherited path
    overwritten with the default; the key left out of either shell's line; the
    printed line taking the default over the terminal's own path (code review,
    2026-10-26: two seats would then lock two files); the default read from
    the temp directory (DEF-4053: two launch contexts whose ``TMPDIR`` differ
    would lock two files)."""

    def test_the_child_gets_the_hosts_default_path_unless_the_parent_named_one(self, seat, tmp_path):
        target = seat.Target("box-x", tmp_path, True, False)
        env = seat.child_env(target, maintenance=False, base={"PATH": "/bin"})
        assert env["ESPALIER_BOX_LOCK"] == str(Path.home() / ".espalier" / "espalier-box.lock")
        env = seat.child_env(target, maintenance=False, base={"PATH": "/bin", "ESPALIER_BOX_LOCK": "/elsewhere/box.lock"})
        assert env["ESPALIER_BOX_LOCK"] == "/elsewhere/box.lock"
        assert seat.BOX_LOCK_KEY == "ESPALIER_BOX_LOCK" and seat.BOX_LOCK_NAME == "espalier-box.lock"

    def test_two_launch_contexts_whose_temp_directories_differ_lock_one_file(self, seat, tmp_path):
        """DEF-4053, the row's probe as a test: the default resolved in two
        child interpreters whose ``TMPDIR`` (and ``TMP``/``TEMP``) differ, as
        a terminal and an app can, is one path. Dies to: the default read
        from ``tempfile.gettempdir()``."""
        code = (f"import sys; sys.path.insert(0, {str(MODULE.parent)!r}); import seat; "
                "print(seat.box_lock_default())")
        seen = set()
        for name in ("one", "two"):
            temp = tmp_path / name
            temp.mkdir()
            out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                                 env={**os.environ, "TMPDIR": str(temp), "TMP": str(temp), "TEMP": str(temp)},
                                 timeout=25, check=True).stdout.strip()   # two under the 60 s ceiling
            assert out and str(temp) not in out, out
            seen.add(out)
        assert len(seen) == 1, seen

    def test_where_no_home_can_be_told_the_default_is_the_temp_directorys(self, seat, monkeypatch):
        """``Path.home`` raises on POSIX with neither ``HOME`` nor a passwd
        entry, and a home that does not expand is no folder: the launcher
        still sets a path, the temp directory's, as before. Dies to: the
        raise escaping into ``launch``, or a relative path set."""
        import tempfile

        def no_home():
            raise RuntimeError("Could not determine home directory.")

        monkeypatch.setattr(seat.Path, "home", staticmethod(no_home))
        assert seat.box_lock_default() == os.path.join(tempfile.gettempdir(), "espalier-box.lock")
        monkeypatch.setattr(seat.Path, "home", staticmethod(lambda: Path("~")))
        assert seat.box_lock_default() == os.path.join(tempfile.gettempdir(), "espalier-box.lock")
        # A container's or a service user's home of "/" (code review): no
        # user can make the folder there, so the temp directory's file stands.
        root = Path(Path.cwd().anchor)
        monkeypatch.setattr(seat.Path, "home", staticmethod(lambda: root))
        assert seat.box_lock_default() == os.path.join(tempfile.gettempdir(), "espalier-box.lock")

    def test_the_posix_line_spells_the_mod_directory_as_the_shell_reads_it(self, seat, tmp_path):
        """A mod directory the shell must quote -- a Windows seat's ``D:\\...``
        (windows-latest red from #351, where the unquoted substring was
        asserted) or a path with a space -- rides the posix print line quoted,
        and the line's reader gets the one argument back. Dies to: an argument
        joined bare, or an expectation spelled as the path alone."""
        import shlex
        mod_dir = tmp_path / "mods" / "own clear"
        (mod_dir / ".claude-plugin").mkdir(parents=True)
        (mod_dir / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
        target = seat.Target("box-x", tmp_path, True, False)
        sh = seat.command_line(target, seat.mod_args(mod_dir), maintenance=False, shell="posix", own_clear=True)
        quoted = shlex.quote(str(mod_dir))
        assert quoted != str(mod_dir), quoted   # the case the Windows cell hits: a path shlex must quote
        assert f"--plugin-dir {quoted}" in sh and f"--plugin-dir {mod_dir}" not in sh, sh
        assert shlex.split(sh.split(" claude ", 1)[1]) == ["--plugin-dir", str(mod_dir)]

    def test_both_shells_lines_carry_the_path_before_claude(self, seat, tmp_path):
        import shlex
        target = seat.Target("box-x", tmp_path, True, False)
        default = str(Path.home() / ".espalier" / "espalier-box.lock")
        sh = seat.command_line(target, ["--model", "o p"], maintenance=False, shell="posix")
        assert f"export ESPALIER_BOX_LOCK=${{ESPALIER_BOX_LOCK:-{shlex.quote(default)}}} && " in sh, sh
        assert sh.index("ESPALIER_BOX_LOCK") < sh.index("claude")
        assert sh.endswith(f"&& env -u ESPALIER_MAINTENANCE_MODE {_own_clear_unsets(seat)} -u ESPALIER_BOX_LOCK_WAIT_S -u VIRTUAL_ENV claude --model 'o p'")
        ps = seat.command_line(target, [], maintenance=False, shell="powershell")
        assert f"if (-not $env:ESPALIER_BOX_LOCK) {{ $env:ESPALIER_BOX_LOCK = '{default}' }}" in ps, ps
        assert ps.index("ESPALIER_BOX_LOCK") < ps.index("claude")


class TestTheLogSwitch:
    """``launch --own-clear-log [PATH]`` (DEF-4057's lane, 2026-10-30): the mod
    appends one JSON line per event to the file ``ESPALIER_OWN_CLEAR_LOG``
    names, and the launcher strips that name from every session it starts, so
    the deferred clear of 2026-10-30 was read from the transcript's queue rows
    instead of the mod's own record. The switch sets the name for the session,
    after the unsets on both printed lines, only when the mod rides; bare, it
    names ``.espalier-state/own_clear.log`` under the seat's checkout -- and
    since DEF-5031 (a clear the engine refused 41 times over ten hours, with
    the log off on every seat) that is the default with the switch left out,
    ``--no-own-clear-log`` the way to a session with no log. Dies to: the name
    set with no mod to write it, a log left exported in the launcher's shell
    riding in, a plain launch with no log, or an assignment rendered before an
    unset on the POSIX line (BSD env stops reading options at the first
    assignment)."""

    def test_the_childs_environment_carries_the_log_only_with_the_mod(self, seat, tmp_path):
        target = seat.Target("box-x", tmp_path, True, False)
        base = {"PATH": "/bin", "ESPALIER_OWN_CLEAR_LOG": "/left/exported.log"}
        env = seat.child_env(target, maintenance=False, base=base, own_clear=True, own_clear_log="/x/own_clear.log")
        assert env["ESPALIER_OWN_CLEAR_LOG"] == "/x/own_clear.log" and env["ESPALIER_OWN_CLEAR"] == "1"
        without_mod = seat.child_env(target, maintenance=False, base=base, own_clear=False, own_clear_log="/x/o.log")
        assert "ESPALIER_OWN_CLEAR_LOG" not in without_mod
        assert "ESPALIER_OWN_CLEAR_LOG" not in seat.child_env(target, maintenance=False, base=base, own_clear=True)

    def test_both_shells_lines_set_the_log_after_the_unsets(self, seat, tmp_path):
        import shlex
        target = seat.Target("box-x", tmp_path, True, False)
        log = str(tmp_path / "state dir" / "own_clear.log")
        sh = seat.command_line(target, [], maintenance=False, shell="posix", own_clear=True, own_clear_log=log)
        assert f"ESPALIER_OWN_CLEAR=1 ESPALIER_OWN_CLEAR_LOG={shlex.quote(log)}" in sh, sh
        assert "-u ESPALIER_OWN_CLEAR_LOG" not in sh and "-u ESPALIER_OWN_CLEAR_ROOT" in sh
        words = sh.split(" env ", 1)[1].split(" claude", 1)[0].split()
        first = next(i for i, w in enumerate(words) if "=" in w)
        assert not [w for w in words[first:] if w.startswith("-")], words
        ps = seat.command_line(target, [], maintenance=False, shell="powershell", own_clear=True, own_clear_log=log)
        assert f"$env:ESPALIER_OWN_CLEAR_LOG = '{log}'" in ps and "Remove-Item Env:ESPALIER_OWN_CLEAR_LOG" not in ps
        assert "Remove-Item Env:ESPALIER_OWN_CLEAR_ROOT" in ps
        plain = seat.command_line(target, [], maintenance=False, shell="posix", own_clear=True)
        assert "ESPALIER_OWN_CLEAR_LOG=" not in plain and "-u ESPALIER_OWN_CLEAR_LOG" in plain

    def test_launch_takes_the_switch_bare_as_the_seats_state_file_and_says_so(self, seat, clone, registry, no_claude,
                                                                             monkeypatch, capsys):
        _dispatcher(clone, '"air"')
        feat = _worktree(clone, "feat", name="box-feat")
        monkeypatch.chdir(clone)
        monkeypatch.setenv("ESPALIER_OWN_CLEAR_LOG", "/left/exported.log")   # never inherited, switch or not
        expected = str(feat / ".espalier-state" / "own_clear.log")
        assert seat.main(["launch", "box-feat", "--own-clear-log", "--", "--model", "x"]) == 0
        env = no_claude[-1]["env"]
        assert env["ESPALIER_OWN_CLEAR_LOG"] == expected and env["ESPALIER_OWN_CLEAR"] == "1"
        assert expected in capsys.readouterr().out
        assert seat.main(["launch", "box-feat", "--own-clear-log", str(feat / "elsewhere.log"), "--", "--model", "x"]) == 0
        assert no_claude[-1]["env"]["ESPALIER_OWN_CLEAR_LOG"] == str(feat / "elsewhere.log")
        capsys.readouterr()
        assert seat.main(["launch", "box-feat", "--no-mod", "--own-clear-log", "--", "--model", "x"]) == 0
        assert "ESPALIER_OWN_CLEAR_LOG" not in no_claude[-1]["env"]
        assert "names nothing without it" in capsys.readouterr().out
        # The default (DEF-5031): the switch left out is the bare switch; the
        # no-mod launch with no switch typed is not told about a switch.
        assert seat.main(["launch", "box-feat", "--", "--model", "x"]) == 0
        assert no_claude[-1]["env"]["ESPALIER_OWN_CLEAR_LOG"] == expected
        assert expected in capsys.readouterr().out
        assert seat.main(["launch", "box-feat", "--no-mod", "--", "--model", "x"]) == 0
        assert "ESPALIER_OWN_CLEAR_LOG" not in no_claude[-1]["env"]
        assert "names nothing without it" not in capsys.readouterr().out
        assert seat.main(["launch", "box-feat", "--own-clear-log", "--print", "--shell", "posix"]) == 0
        assert f"ESPALIER_OWN_CLEAR_LOG={seat.shlex.quote(expected)}" in capsys.readouterr().out

    def test_no_own_clear_log_starts_the_session_with_no_log(self, seat, clone, registry, no_claude, monkeypatch,
                                                              capsys):
        """The one way to a session the mod does not log (DEF-5031 turned the
        default on): the name is unset on both printed lines as before, and the
        launch line says the mod rides without a log."""
        _dispatcher(clone, '"air"')
        _worktree(clone, "feat", name="box-feat")
        monkeypatch.chdir(clone)
        monkeypatch.setenv("ESPALIER_OWN_CLEAR_LOG", "/left/exported.log")
        assert seat.main(["launch", "box-feat", "--no-own-clear-log", "--", "--model", "x"]) == 0
        env = no_claude[-1]["env"]
        assert "ESPALIER_OWN_CLEAR_LOG" not in env and env["ESPALIER_OWN_CLEAR"] == "1"
        out = capsys.readouterr().out
        assert "own-clear mod loaded" in out and "its log:" not in out
        assert seat.main(["launch", "box-feat", "--no-own-clear-log", "--print", "--shell", "posix"]) == 0
        line = capsys.readouterr().out
        assert "-u ESPALIER_OWN_CLEAR_LOG" in line and "ESPALIER_OWN_CLEAR_LOG=" not in line

    def test_a_relative_log_path_is_resolved_where_the_operator_typed_it(self, seat, clone, registry, no_claude,
                                                                          monkeypatch):
        """The session's own directory is the seat's checkout, so a relative
        path handed through would land there as an untracked file (the
        failure-mode review); it is resolved where the operator typed it."""
        _dispatcher(clone, '"air"')
        _worktree(clone, "feat", name="box-feat")
        monkeypatch.chdir(clone)
        assert seat.main(["launch", "box-feat", "--own-clear-log", "logs/oc.log", "--", "--model", "x"]) == 0
        assert no_claude[-1]["env"]["ESPALIER_OWN_CLEAR_LOG"] == os.path.abspath("logs/oc.log")
