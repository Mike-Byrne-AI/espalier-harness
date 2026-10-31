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

    def add(cwd: Path, *, pid: int | None = None, entrypoint: str = "cli") -> int:
        pid = pid or os.getpid()
        (cfg / "sessions" / f"{pid}.json").write_text(json.dumps(
            {"pid": pid, "sessionId": f"s{pid}", "cwd": str(cwd), "kind": "interactive",
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
        assert sh.endswith(f"&& env -u ESPALIER_MAINTENANCE_MODE {_own_clear_unsets(seat)} -u VIRTUAL_ENV claude --model 'o p'")
        bindir = target.path / ".venv" / ("Scripts" if os.name == "nt" else "bin")
        bindir.mkdir(parents=True)
        with_venv = seat.command_line(target, [], maintenance=False, shell="powershell")
        assert f"$env:PATH = '{str(bindir).replace(chr(39), chr(39) * 2)};' + $env:PATH" in with_venv
        posix_venv = seat.command_line(target, [], maintenance=True, shell="posix")
        assert f"env {_own_clear_unsets(seat)} ESPALIER_MAINTENANCE_MODE=1 VIRTUAL_ENV=" in posix_venv and ':"$PATH" claude' in posix_venv

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
        assert sh.endswith(f"&& env {_own_clear_unsets(seat)} -u VIRTUAL_ENV ESPALIER_MAINTENANCE_MODE=1 claude"), sh
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
#: stopped seat). The self-host render must reproduce it byte for byte; its 15
#: minutes is DISPATCHER_TICK's interval, rendered, never copied.
_OPERATOR_TICK = (
    "/loop 10m Worker tick. Run /inbox (mark read) and /inbox board and read live state. Act only on what is "
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
    "(an operator call by its id), and only re-read mail until an ack frees or re-aims you or what stops you is "
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
        assert brief.role == "worker" and loop == brief.loop == _OPERATOR_TICK
        assert first.startswith("You are seat box-feat, a worker under the dispatcher air (Core Rule 15, "
                                "memory/parallel-work-protocol.md). Orient from the banner, then run /inbox")
        assert first.endswith("Then start the worker loop on the next line with no further message from the operator.")

    def test_an_adopter_worker_is_pointed_at_what_its_checkout_holds(self, seat, clone):
        _dispatcher(clone, '"hub"')
        feat = _worktree(clone, "feat", name="box-feat")
        _holds(feat, "docs/WORKFLOW.md")
        seeded = seat.compose_brief(clone, "box-feat", feat)
        assert "a worker under the dispatcher hub (docs/WORKFLOW.md, Parallel seats)." in seeded.text
        assert "the proof the change earns per /implement-task step 7" in seeded.loop and "--base" not in seeded.text
        assert ("the reviewers the diff earns, dispatched at once with your edits frozen, per "
                "/implement-task step 6") in seeded.loop
        assert "snapshot clone" not in seeded.text   # defined on this repository only
        assert "note from hub;" in seeded.loop and "send hub one request" in seeded.loop
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
        assert "note from the operator;" in brief.loop and "send the operator one request" in brief.loop

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
        assert brief.role == "dispatcher" and loop == brief.loop == "/loop 15m /inbox board"
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
        ack, instead of filing an operator call and waiting; the operator can
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
                "word; an ack opening with RULING or an address is not counted; one ruling per ack) and carries "
                "the facts you read, "
                "instead of filing an operator call and waiting (scripts/seat_day_census.py counts the rulings "
                "by that opening and your row names them); the operator can reverse it, and a new pack, a scope "
                "change, a release or tag stay the operator's. A (stopped) row on the asks line past the hour is "
                "that read: answer it with the ack that frees or re-aims the seat. A red main no revert clears is "
                "ruled the same way: the ack's text opens with the fixed head gridlock: fix forward run <the red "
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
                "call by its id), and only re-read mail until an ack frees or re-aims you or what stops you is gone, "
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
        Rule 15 and the inbox body's ruling paragraph. Dies to: the brief
        saying the ack carries the facts with no marker, the marker spelled
        apart from the table in any clause, or a record home that names the
        ruling without the word."""
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
        assert (f"rule, act and report the ruling as an ack whose text opens with {marker} (its first word; an "
                "ack opening with RULING or an address is not counted; one ruling per ack) and carries the facts "
                "you read, instead "
                "of filing an operator call and waiting (scripts/seat_day_census.py counts the rulings by that "
                "opening and your row names them); the operator can reverse it") in seat.SELF_HOST_GRIDLOCK
        assert f"an ack from {{dispatcher}} beginning {census.MARKERS['redirect']} re-aims" in seat.SELF_HOST_PROCEED
        assert f"one note beginning {census.MARKERS['shelved']} says" in seat.SELF_HOST_PROCEED
        protocol = (root / "memory" / "parallel-work-protocol.md").read_text(encoding="utf-8")
        start = protocol.index("**Assign authority")
        paragraph = " ".join(protocol[start:protocol.index("\n\n", start)].split())
        assert f"The ruling's `ack` opens with `{marker}`" in paragraph, paragraph
        assert "names each ruling's id" in paragraph, paragraph
        row = next((line for line in protocol.splitlines() if line.startswith("| Resolves a gridlock")), "")
        assert f"an `ack` opening with `{marker}`" in row, row
        rule = next(line for line in (root / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
                    if line.startswith("15. **Parallel work"))
        assert f"as an ack opening with `{marker}`" in rule, rule
        raw = (root / ".claude" / "commands" / "inbox.md").read_text(encoding="utf-8")
        inbox = " ".join(raw.split())
        assert f"whose text opens with `{marker}`" in inbox
        assert "seat-day census counts a ruling by that opening on the dispatcher's acks alone" in inbox
        assert f'--text "{marker} <the ruling, the facts you read>"' in inbox
        # The rule renders on this repository alone (the brief's slot is empty elsewhere), so the
        # inbox body says it inside a self-host block that the asset deploy strips.
        from espalier.surface_hygiene import strip_self_host_blocks
        assert marker not in strip_self_host_blocks(raw) and "Core Rule 15" not in strip_self_host_blocks(raw)

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
        for name in ("WORKER_BRIEF", "DISPATCHER_BRIEF", "WORKER_TICK", "SELF_HOST_PROCEED"):
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
        loop = seat.compose_brief(clone, "box-feat", feat).loop
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
        for template in (seat.WORKER_TICK, seat.SELF_HOST_PROCEED, seat.ADOPTER_PROCEED, seat.DISPATCHER_BRIEF):
            assert re.search(r"\d+ minutes", template) is None, template
        _dispatcher(clone, '"air"')
        feat = _worktree(clone, "feat", name="box-feat")
        _holds(feat, "memory/parallel-work-protocol.md", "scripts/proof_tier.py")
        loop = seat.compose_brief(clone, "box-feat", feat).loop
        assert f"proceed on it after {minutes} minutes (the dispatcher's tick" in loop
        assert "run mail.py refresh once" in loop and "{" not in loop
        dispatcher = seat.compose_brief(clone, "air", clone).text
        assert f"read the board every {minutes} minutes" in dispatcher and "{" not in dispatcher

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
        loop = seat.compose_brief(clone, "box-feat", feat).loop
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
        assert "the reviewers the diff earns" in seat.compose_brief(clone, "box-feat", feat).loop
        _holds(feat, "memory/parallel-work-protocol.md")
        # the protocol alone: no script to print the line, so step 6's rule
        assert "the reviewers the diff earns" in seat.compose_brief(clone, "box-feat", feat).loop
        _holds(feat, "scripts/proof_tier.py")
        loop = seat.compose_brief(clone, "box-feat", feat).loop
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



class TestTheLauncherSetsTheBoxLock:
    """A seat launched by the tool, or by its printed line, runs under the box
    lock: ``ESPALIER_BOX_LOCK`` names one path per host under the temp
    directory unless the parent already named one, so two seats on one box
    take the same lock and CI, which never runs the launcher, never sees it.
    Mutations: the key dropped from the child's environment; an inherited path
    overwritten with the default; the key left out of either shell's line; the
    printed line taking the default over the terminal's own path (code review,
    2026-10-26: two seats would then lock two files)."""

    def test_the_child_gets_the_hosts_default_path_unless_the_parent_named_one(self, seat, tmp_path):
        import tempfile
        target = seat.Target("box-x", tmp_path, True, False)
        env = seat.child_env(target, maintenance=False, base={"PATH": "/bin"})
        assert env["ESPALIER_BOX_LOCK"] == os.path.join(tempfile.gettempdir(), "espalier-box.lock")
        env = seat.child_env(target, maintenance=False, base={"PATH": "/bin", "ESPALIER_BOX_LOCK": "/elsewhere/box.lock"})
        assert env["ESPALIER_BOX_LOCK"] == "/elsewhere/box.lock"
        assert seat.BOX_LOCK_KEY == "ESPALIER_BOX_LOCK" and seat.BOX_LOCK_NAME == "espalier-box.lock"

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
        import tempfile
        target = seat.Target("box-x", tmp_path, True, False)
        default = os.path.join(tempfile.gettempdir(), "espalier-box.lock")
        sh = seat.command_line(target, ["--model", "o p"], maintenance=False, shell="posix")
        assert f"export ESPALIER_BOX_LOCK=${{ESPALIER_BOX_LOCK:-{shlex.quote(default)}}} && " in sh, sh
        assert sh.index("ESPALIER_BOX_LOCK") < sh.index("claude")
        assert sh.endswith(f"&& env -u ESPALIER_MAINTENANCE_MODE {_own_clear_unsets(seat)} -u VIRTUAL_ENV claude --model 'o p'")
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
