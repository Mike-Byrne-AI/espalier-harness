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


@pytest.fixture(scope="module")
def seat():
    spec = importlib.util.spec_from_file_location("seat_under_test", MODULE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _outside_a_session(monkeypatch):
    """The suite may run inside a Claude session; the oracle then insists the
    registry list it. These cases are about the seat, not the caller."""
    monkeypatch.delenv("CLAUDECODE", raising=False)


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
    """Record the one spawn instead of running claude."""
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

class TestLaunch:
    def test_an_occupied_seat_is_refused_and_a_gone_session_is_not_occupancy(self, seat, clone, registry, no_claude,
                                                                             capsys):
        """The pack's red. Dies to: dropping the cwd comparison from the
        liveness oracle (launch then proceeds into an occupied checkout)."""
        feat = _worktree(clone, "feat", name="box-feat")
        pid = registry(feat / "src")
        with pytest.raises(seat.Refused) as refused:
            seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=True)
        assert str(refused.value).startswith(f"seat box-feat is occupied: pid {pid} (cli, started 2026-10-15 06:30Z) "
                                             f"is in {feat}")
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
        assert call["argv"] == ["/fake/bin/claude", "--model", "x"] and Path(call["cwd"]) == path
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
        out = capsys.readouterr().out.strip().splitlines()[-1]
        assert "claude" in out and ("'o p'" in out)
        assert seat.split_claude_args(["launch", "x", "--", "--print"]) == (["launch", "x"], ["--print"])

    def test_names_that_are_no_seat_are_refused(self, seat, clone, tmp_path):
        with pytest.raises(seat.Refused, match="no seat 'nobody' here: this clone is 'box'"):
            seat.resolve(clone, "nobody")
        stray = clone / ".claude" / "worktrees" / "stray"
        stray.mkdir(parents=True)
        with pytest.raises(seat.Refused, match="git does not register it as a worktree answering 'box-stray'"):
            seat.resolve(clone, "box-stray")
        _git(clone, "config", "--unset", "espalier.machine")
        with pytest.raises(seat.Refused, match="this clone names no machine"):
            seat.resolve(clone, "box")

    def test_the_command_line_is_quoted_for_each_shell(self, seat, tmp_path):
        target = seat.Target("box-x", tmp_path / "it's here", True, False)
        ps = seat.command_line(target, ["--model", "o p"], maintenance=True, windows=True)
        assert ps.startswith(f"Set-Location -LiteralPath '{str(tmp_path / 'it')}''s here'; ")
        assert "$env:ESPALIER_MAINTENANCE_MODE = '1'" in ps and ps.endswith("claude '--model' 'o p'")
        assert "Remove-Item Env:ESPALIER_MAINTENANCE_MODE" in seat.command_line(target, [], maintenance=False,
                                                                                windows=True)
        sh = seat.command_line(target, ["--model", "o p"], maintenance=False, windows=False)
        assert sh.endswith("&& env -u ESPALIER_MAINTENANCE_MODE claude --model 'o p'")


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

    def test_jobs_are_named_and_left_to_the_dispatcher(self, seat, clone, registry, capsys):
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, clone, "box", "assign", "build it", lane="lane/next", seat="box-feat")
        assert seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True) == 0
        assert "still assigned to box-feat: lane/next" in capsys.readouterr().out
        by_machine, _ = seat.mail.read_mail(clone)
        assert [j["re"]["lane"] for j in seat.mail.live_assignments(by_machine)] == ["lane/next"]
        assert not feat.exists()

    def test_a_dead_holders_lock_is_released_and_said(self, seat, clone, registry, capsys):
        feat = _worktree(clone, "feat", name="box-feat")
        gone = _dead_pid()
        _git(clone, "worktree", "lock", "--reason", f"claude session feat (pid {gone})", str(feat))
        assert seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=False) == 0
        assert f"unlocked feat (pid {gone}): the lock's holder has exited" in capsys.readouterr().out

    def test_a_seat_whose_worktree_is_gone_gets_the_recipe(self, seat, clone, registry):
        gone = _worktree(clone, "gone", name="box-gone")
        _send(seat, gone, "box-gone", "claim", "lost", lane="lane/gone")
        _git(clone, "worktree", "remove", "--force", str(gone))
        with pytest.raises(seat.Refused) as refused:
            seat.cmd_retire(clone, "box-gone", dry_run=False, fetch=True)
        said = str(refused.value)
        assert said.startswith("seat box-gone holds 1 live claim(s) and its worktree is gone")
        assert "git worktree add --detach .claude/worktrees/gone origin/main" in said
        assert "git -C .claude/worktrees/gone config --worktree espalier.machine box-gone" in said
        assert "python tools/cc/mail.py send --type release --lane lane/gone" in said

    def test_the_clone_itself_is_never_retired_and_a_dry_run_changes_nothing(self, seat, clone, registry, capsys):
        with pytest.raises(seat.Refused, match="box is the clone itself"):
            seat.cmd_retire(clone, "box", dry_run=False, fetch=False)
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat")
        seat.cmd_retire(clone, "box-feat", dry_run=True, fetch=True)
        out = capsys.readouterr().out
        assert "dry-run: would release 1 claim(s) of box-feat (lane/feat)" in out
        assert feat.is_dir() and len(_live_claims_from(seat, clone, "box-feat")) == 1
